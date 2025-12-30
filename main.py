import asyncio
from fastapi import FastAPI, Depends, HTTPException, status, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy import func, or_, and_
from sqlalchemy.orm import Session
from typing import Dict, List, Optional, Set
from jose import JWTError, jwt
from datetime import datetime, timedelta
from pydantic import BaseModel
import json
import models
import auth
from database import engine, get_db, SessionLocal
import traceback

# Создаем таблицы
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="ВРаботе API", version="1.0.0")

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8081",
        "http://localhost:19006",
        "exp://192.168.10.106:8081",
        "http://192.168.10.106:19006",
        "http://192.168.10.106:19000",
        "*"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Схема OAuth2
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# WebSocket менеджер
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.user_rooms: Dict[str, Set[str]] = {}

    async def connect(self, websocket: WebSocket, client_id: str, room_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket
        if client_id not in self.user_rooms:
            self.user_rooms[client_id] = set()
        self.user_rooms[client_id].add(room_id)
        print(f"✅ Client {client_id} connected to room {room_id}")

    def disconnect(self, client_id: str, room_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
        if client_id in self.user_rooms and room_id in self.user_rooms[client_id]:
            self.user_rooms[client_id].remove(room_id)
        print(f"❌ Client {client_id} disconnected from room {room_id}")

    async def send_personal_message(self, message: dict, client_id: str):
        if client_id in self.active_connections:
            try:
                await self.active_connections[client_id].send_json(message)
            except Exception as e:
                print(f"Error sending to client {client_id}: {e}")

    async def broadcast_to_room(self, message: dict, room_id: str, exclude_client_id: str = None):
        for client_id, rooms in self.user_rooms.items():
            if room_id in rooms and client_id != exclude_client_id:
                await self.send_personal_message(message, client_id)

manager = ConnectionManager()

# Модели Pydantic
class OrderCreate(BaseModel):
    title: str
    description: str
    requirements: str
    budget: float
    deadline: Optional[datetime] = None
    category: Optional[str] = "other"

class OrderResponse(BaseModel):
    id: int
    title: str
    description: str
    requirements: str
    budget: float
    status: str
    created_at: datetime
    client_id: int
    deadline: Optional[datetime] = None
    freelancer_id: Optional[int] = None
    category: Optional[str] = None

    class Config:
        from_attributes = True

class BidCreate(BaseModel):
    order_id: int
    amount: float
    proposal: str
    portfolio_links: Optional[str] = None

class BidResponse(BaseModel):
    id: int
    order_id: int
    freelancer_id: int
    amount: float
    proposal: str
    status: str
    created_at: datetime
    portfolio_links: Optional[str] = None
    freelancer_name: Optional[str] = None
    order_title: Optional[str] = None

    class Config:
        from_attributes = True

class ChatMessageCreate(BaseModel):
    message: str
    message_type: str = "text"

class ReviewCreate(BaseModel):
    order_id: int
    rating: int
    comment: str

class ReviewReply(BaseModel):
    reply_text: str

class NotificationResponse(BaseModel):
    id: int
    title: str
    body: str
    notification_type: str
    related_id: Optional[int]
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True

# Вспомогательная функция для получения текущего пользователя
async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, auth.SECRET_KEY, algorithms=[auth.ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    user = db.query(models.User).filter(models.User.email == email).first()
    if user is None:
        raise credentials_exception
    return user

# Вспомогательная функция для создания уведомлений
def create_notification(db: Session, user_id: int, title: str, body: str, notif_type: str, related_id: int = None):
    notification = models.Notification(
        user_id=user_id,
        title=title,
        body=body,
        notification_type=notif_type,
        related_id=related_id
    )
    db.add(notification)
    return notification

# WebSocket endpoint
@app.websocket("/ws/{order_id}")
async def websocket_endpoint(websocket: WebSocket, order_id: int):
    await websocket.accept()
    client_id = None
    user_id = None
    
    try:
        # Получаем токен из query параметров
        token = websocket.query_params.get("token")
        if not token:
            print("❌ No token provided in WebSocket connection")
            await websocket.close(code=1008, reason="No token provided")
            return
        
        print(f"🔑 Token received: {token[:20]}...")
            
        # Верифицируем токен
        try:
            payload = jwt.decode(token, auth.SECRET_KEY, algorithms=[auth.ALGORITHM])
            user_email = payload.get("sub")
            
            if not user_email:
                print("❌ No email in token payload")
                await websocket.close(code=1008, reason="Invalid token: no email")
                return
            
            db = SessionLocal()
            user = db.query(models.User).filter(models.User.email == user_email).first()
            db.close()
            
            if not user:
                print(f"❌ User not found for email: {user_email}")
                await websocket.close(code=1008, reason="User not found")
                return
                
            user_id = user.id
            client_id = f"user_{user_id}_order_{order_id}"
            
            print(f"✅ User authenticated: {user_email} (ID: {user_id})")
            
        except jwt.ExpiredSignatureError:
            print("❌ Token expired")
            await websocket.close(code=1008, reason="Token expired")
            return
        except jwt.JWTError as e:
            print(f"❌ JWT error: {e}")
            await websocket.close(code=1008, reason=f"Invalid token: {str(e)}")
            return
        except Exception as e:
            print(f"❌ Token verification error: {e}")
            await websocket.close(code=1008, reason="Token verification failed")
            return
        
        # Проверяем, имеет ли пользователь доступ к этому заказу
        db = SessionLocal()
        order = db.query(models.Order).filter(models.Order.id == order_id).first()
        db.close()
        
        if not order:
            print(f"❌ Order {order_id} not found")
            await websocket.close(code=1008, reason="Order not found")
            return
            
        # Проверяем права доступа к заказу
        if user_id not in [order.client_id, order.freelancer_id]:
            print(f"❌ User {user_id} has no access to order {order_id}")
            await websocket.close(code=1008, reason="No access to this order")
            return
        
        room_id = f"order_{order_id}"
        
        # Подключаем пользователя
        await manager.connect(websocket, client_id, room_id)
        
        # Отправляем подтверждение подключения
        await websocket.send_json({
            "type": "connection_established",
            "message": "WebSocket connected successfully",
            "user_id": user_id,
            "order_id": order_id
        })
        
        print(f"✅ WebSocket connection established for user {user_id} to order {order_id}")
        
        # Отправляем историю сообщений
        db = SessionLocal()
        messages = db.query(models.ChatMessage).filter(
            models.ChatMessage.order_id == order_id
        ).order_by(models.ChatMessage.created_at.desc()).limit(20).all()
        db.close()
        
        # Отправляем сообщения в обратном порядке (от старых к новым)
        for msg in reversed(messages):
            try:
                await websocket.send_json({
                    "type": "new_message",
                    "id": msg.id,
                    "sender_id": msg.sender_id,
                    "message": msg.message,
                    "created_at": msg.created_at.isoformat(),
                    "is_own": msg.sender_id == user_id
                })
            except Exception as e:
                print(f"Error sending message history: {e}")
        
        # Основной цикл обработки сообщений
        try:
            while True:
                # Ждем сообщения от клиента с таймаутом
                try:
                    data = await asyncio.wait_for(websocket.receive_json(), timeout=300.0)
                except asyncio.TimeoutError:
                    # Отправляем ping, чтобы проверить соединение
                    try:
                        await websocket.send_json({"type": "ping"})
                        continue
                    except:
                        break  # Соединение разорвано
                
                print(f"📨 Received WebSocket message: {data}")
                
                if data.get("type") == "message":
                    # Сохраняем в базу
                    db = SessionLocal()
                    try:
                        message_text = data.get("message", "").strip()
                        if not message_text:
                            await websocket.send_json({
                                "type": "error",
                                "message": "Empty message"
                            })
                            continue
                            
                        message = models.ChatMessage(
                            order_id=order_id,
                            sender_id=user_id,
                            message=message_text,
                            message_type=data.get("message_type", "text")
                        )
                        db.add(message)
                        db.commit()
                        db.refresh(message)
                        
                        # Рассылаем всем в комнате
                        await manager.broadcast_to_room({
                            "type": "new_message",
                            "id": message.id,
                            "sender_id": user_id,
                            "message": message.message,
                            "created_at": message.created_at.isoformat(),
                            "is_own": False
                        }, room_id, client_id)
                        
                        # Подтверждение отправителю
                        await websocket.send_json({
                            "type": "message_sent",
                            "id": message.id,
                            "created_at": message.created_at.isoformat()
                        })
                        
                    except Exception as e:
                        print(f"Error saving message: {e}")
                        await websocket.send_json({
                            "type": "error",
                            "message": "Failed to save message"
                        })
                    finally:
                        db.close()
                
                elif data.get("type") == "ping":
                    # Отвечаем на ping
                    await websocket.send_json({"type": "pong"})
                
                elif data.get("type") == "join":
                    # Уже подключены
                    await websocket.send_json({
                        "type": "join_confirmed",
                        "user_id": user_id,
                        "order_id": order_id
                    })
                    
        except WebSocketDisconnect:
            print(f"WebSocket disconnected normally for client {client_id}")
        except Exception as e:
            print(f"WebSocket error in message loop: {e}")
                
    except WebSocketDisconnect:
        print(f"WebSocket disconnected during setup for client {client_id}")
    except Exception as e:
        print(f"WebSocket endpoint error: {e}")
    finally:
        if client_id:
            manager.disconnect(client_id, f"order_{order_id}")
        print(f"❌ WebSocket connection closed for order {order_id}")

# Регистрация пользователя
@app.post("/register", response_model=auth.UserResponse)
def register(user: auth.UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(models.User).filter(models.User.email == user.email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    hashed_password = auth.get_password_hash(user.password)
    db_user = models.User(
        email=user.email,
        full_name=user.full_name,
        hashed_password=hashed_password,
        is_freelancer=user.is_freelancer
    )
    
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

# Вход пользователя
@app.post("/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == form_data.username).first()
    if not user or not auth.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=auth.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = auth.create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "is_freelancer": user.is_freelancer
    }

# Создание заказа
@app.post("/orders", response_model=OrderResponse)
async def create_order(order: OrderCreate, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.is_freelancer:
        raise HTTPException(status_code=400, detail="Freelancers cannot create orders")
    
    db_order = models.Order(
        title=order.title,
        description=order.description,
        requirements=order.requirements,
        budget=order.budget,
        client_id=current_user.id,
        deadline=order.deadline,
        category=order.category
    )
    
    db.add(db_order)
    db.commit()
    db.refresh(db_order)
    
    # Уведомления для фрилансеров
    freelancers = db.query(models.User).filter(
        models.User.is_freelancer == True,
        models.User.is_active == True
    ).limit(20).all()
    
    for freelancer in freelancers:
        create_notification(
            db,
            freelancer.id,
            "Новый заказ в вашей ленте",
            f"Появился новый заказ: '{order.title}' за {order.budget} руб.",
            "new_order",
            db_order.id
        )
    
    db.commit()
    return db_order

# Получение всех заказов (с пагинацией)
@app.get("/orders", response_model=List[OrderResponse])
async def get_orders_paginated(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        skip = (page - 1) * limit
        
        if current_user.is_freelancer:
            # Для фрилансера показываем только открытые заказы
            query = db.query(models.Order).filter(
                models.Order.status == "open"
            )
        else:
            # Для клиента показываем все его заказы
            query = db.query(models.Order).filter(
                models.Order.client_id == current_user.id
            )
        
        orders = query.order_by(
            # Приоритет: премиум -> срочные -> обычные
            models.Order.is_premium.desc(),
            models.Order.is_urgent.desc(),
            models.Order.created_at.desc()
        ).offset(skip).limit(limit).all()
        
        return orders
    except Exception as e:
        print(f"Error in get_orders_paginated: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Internal server error")

# Получение заказа по ID
@app.get("/orders/{order_id}", response_model=OrderResponse)
def get_order(order_id: int, db: Session = Depends(get_db)):
    try:
        print(f"🔄 Запрос на /orders/{order_id}")
        order = db.query(models.Order).filter(models.Order.id == order_id).first()
        if order is None:
            raise HTTPException(status_code=404, detail="Order not found")
        return order
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in get_order: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Internal server error")

# Получение заказов пользователя (с пагинацией)
@app.get("/my-orders", response_model=List[OrderResponse])
async def get_my_orders_paginated(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        skip = (page - 1) * limit
        
        if current_user.is_freelancer:
            orders = db.query(models.Order).filter(
                models.Order.freelancer_id == current_user.id,
                models.Order.status != "cancelled"
            )
        else:
            orders = db.query(models.Order).filter(
                models.Order.client_id == current_user.id,
                models.Order.status != "cancelled"
            )
        
        orders = orders.order_by(
            models.Order.created_at.desc()
        ).offset(skip).limit(limit).all()
        
        return orders
    except Exception as e:
        print(f"Error in get_my_orders_paginated: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Internal server error")

# Получение отклика по ID
@app.get("/bids/{bid_id}", response_model=BidResponse)
async def get_bid(bid_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        bid = db.query(models.Bid).filter(models.Bid.id == bid_id).first()
        if not bid:
            raise HTTPException(status_code=404, detail="Bid not found")
        
        # Проверяем права доступа
        order = db.query(models.Order).filter(models.Order.id == bid.order_id).first()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        
        # Только участники заказа могут видеть отклик
        if current_user.id not in [order.client_id, order.freelancer_id, bid.freelancer_id]:
            raise HTTPException(status_code=403, detail="Not authorized")
        
        # Добавляем информацию об исполнителе и заказе
        freelancer = db.query(models.User).filter(models.User.id == bid.freelancer_id).first()
        bid_data = {
            "id": bid.id,
            "order_id": bid.order_id,
            "freelancer_id": bid.freelancer_id,
            "amount": bid.amount,
            "proposal": bid.proposal,
            "status": bid.status,
            "created_at": bid.created_at,
            "portfolio_links": bid.portfolio_links,
            "freelancer_name": freelancer.full_name if freelancer else "Неизвестный исполнитель",
            "order_title": order.title
        }
        
        return bid_data
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in get_bid: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Internal server error")

# Создание отклика на заказ
@app.post("/bids", response_model=BidResponse)
async def create_bid(bid: BidCreate, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        order = db.query(models.Order).filter(models.Order.id == bid.order_id).first()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        
        if not current_user.is_freelancer:
            raise HTTPException(status_code=400, detail="Only freelancers can create bids")
        
        if order.status != "open":
            raise HTTPException(status_code=400, detail="Order is not open for bidding")
        
        existing_bid = db.query(models.Bid).filter(
            models.Bid.order_id == bid.order_id,
            models.Bid.freelancer_id == current_user.id
        ).first()
        
        if existing_bid:
            raise HTTPException(status_code=400, detail="You have already bid on this order")
        
        db_bid = models.Bid(
            order_id=bid.order_id,
            freelancer_id=current_user.id,
            amount=bid.amount,
            proposal=bid.proposal,
            portfolio_links=bid.portfolio_links
        )
        
        db.add(db_bid)
        
        # Получаем количество откликов на этот заказ
        bid_count = db.query(models.Bid).filter(
            models.Bid.order_id == bid.order_id
        ).count()
        
        # Уведомление клиенту
        create_notification(
            db,
            order.client_id,
            f"Новый отклик на ваш заказ ({bid_count} всего)",
            f"На ваш заказ '{order.title}' поступил новый отклик за {bid.amount} руб.",
            "new_bid",
            db_bid.id
        )
        
        db.commit()
        db.refresh(db_bid)
        
        # Добавляем информацию об исполнителе
        bid_response = {
            "id": db_bid.id,
            "order_id": db_bid.order_id,
            "freelancer_id": db_bid.freelancer_id,
            "amount": db_bid.amount,
            "proposal": db_bid.proposal,
            "status": db_bid.status,
            "created_at": db_bid.created_at,
            "portfolio_links": db_bid.portfolio_links,
            "freelancer_name": current_user.full_name,
            "order_title": order.title
        }
        
        return bid_response
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f"Error in create_bid: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Internal server error")

# Получение откликов пользователя
@app.get("/my-bids", response_model=List[BidResponse])
async def get_my_bids(current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    bids = db.query(models.Bid).filter(models.Bid.freelancer_id == current_user.id).all()
    
    # Добавляем информацию об исполнителе и заказе
    result = []
    for bid in bids:
        freelancer = db.query(models.User).filter(models.User.id == bid.freelancer_id).first()
        order = db.query(models.Order).filter(models.Order.id == bid.order_id).first()
        
        bid_data = {
            "id": bid.id,
            "order_id": bid.order_id,
            "freelancer_id": bid.freelancer_id,
            "amount": bid.amount,
            "proposal": bid.proposal,
            "status": bid.status,
            "created_at": bid.created_at,
            "portfolio_links": bid.portfolio_links,
            "freelancer_name": freelancer.full_name if freelancer else "Неизвестный исполнитель",
            "order_title": order.title if order else "Неизвестный заказ"
        }
        result.append(bid_data)
    
    return result

# Получение откликов на заказ
@app.get("/orders/{order_id}/bids", response_model=List[BidResponse])
async def get_order_bids(
    order_id: int, 
    current_user: models.User = Depends(get_current_user), 
    db: Session = Depends(get_db)
):
    try:
        order = db.query(models.Order).filter(models.Order.id == order_id).first()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        
        # Разрешаем просмотр откликов автору заказа
        if order.client_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not authorized to view bids for this order")
        
        bids = db.query(models.Bid).filter(models.Bid.order_id == order_id).all()
        
        # Добавляем информацию об исполнителе
        result = []
        for bid in bids:
            freelancer = db.query(models.User).filter(models.User.id == bid.freelancer_id).first()
            
            bid_data = {
                "id": bid.id,
                "order_id": bid.order_id,
                "freelancer_id": bid.freelancer_id,
                "amount": bid.amount,
                "proposal": bid.proposal,
                "status": bid.status,
                "created_at": bid.created_at,
                "portfolio_links": bid.portfolio_links,
                "freelancer_name": freelancer.full_name if freelancer else "Неизвестный исполнитель",
                "order_title": order.title
            }
            result.append(bid_data)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in get_order_bids: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Internal server error")

# Принятие отклика
@app.patch("/bids/{bid_id}/accept")
async def accept_bid(bid_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    bid = db.query(models.Bid).filter(models.Bid.id == bid_id).first()
    if not bid:
        raise HTTPException(status_code=404, detail="Bid not found")
    
    order = db.query(models.Order).filter(models.Order.id == bid.order_id).first()
    if order.client_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to accept this bid")
    
    if order.status != "open":
        raise HTTPException(status_code=400, detail="Order is not open")
    
    # Обновляем статус бида
    bid.status = "accepted"
    
    # Обновляем заказ
    order.status = "in_progress"
    order.freelancer_id = bid.freelancer_id
    
    # Отклоняем остальные отклики
    rejected_bids = db.query(models.Bid).filter(
        models.Bid.order_id == bid.order_id,
        models.Bid.id != bid_id
    ).all()
    
    for rejected_bid in rejected_bids:
        rejected_bid.status = "rejected"
        create_notification(
            db,
            rejected_bid.freelancer_id,
            "Отклик отклонен",
            f"Ваш отклик на заказ '{order.title}' был отклонен",
            "bid_rejected",
            order.id
        )
    
    # Уведомление фрилансеру о принятии
    create_notification(
        db,
        bid.freelancer_id,
        "Ваш отклик принят!",
        f"Клиент принял ваш отклик на заказ '{order.title}' за {bid.amount} руб. Теперь вы можете обсудить детали в чате.",
        "bid_accepted",
        order.id
    )
    
    # Уведомление клиенту
    create_notification(
        db,
        order.client_id,
        "Отклик принят",
        f"Вы приняли отклик от исполнителя на заказ '{order.title}'. Теперь вы можете обсудить детали в чате.",
        "bid_accepted",
        order.id
    )
    
    db.commit()
    return {"message": "Bid accepted successfully", "bid_id": bid_id, "order_id": order.id}

# Отклонение отклика
@app.patch("/bids/{bid_id}/reject")
async def reject_bid(bid_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    bid = db.query(models.Bid).filter(models.Bid.id == bid_id).first()
    if not bid:
        raise HTTPException(status_code=404, detail="Bid not found")
    
    order = db.query(models.Order).filter(models.Order.id == bid.order_id).first()
    if order.client_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to reject this bid")
    
    if bid.status != "pending":
        raise HTTPException(status_code=400, detail="Bid is not pending")
    
    bid.status = "rejected"
    
    create_notification(
        db,
        bid.freelancer_id,
        "Отклик отклонен",
        f"Ваш отклик на заказ '{order.title}' был отклонен клиентом",
        "bid_rejected",
        order.id
    )
    
    db.commit()
    return {"message": "Bid rejected successfully", "bid_id": bid_id}

# Завершение заказа
@app.patch("/orders/{order_id}/complete")
async def complete_order(order_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    if order.client_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only client can complete order")
    
    if order.status != "in_progress":
        raise HTTPException(status_code=400, detail="Order is not in progress")
    
    order.status = "completed"
    
    create_notification(
        db,
        order.freelancer_id,
        "Заказ завершен!",
        f"Заказ '{order.title}' был завершен клиентом. Вы можете оставить отзыв.",
        "order_completed",
        order.id
    )
    
    create_notification(
        db,
        order.client_id,
        "Заказ завершен",
        f"Вы успешно завершили заказ '{order.title}'.",
        "order_completed",
        order.id
    )
    
    db.commit()
    return {"message": "Order completed successfully", "order_id": order_id}

# Отмена заказа
@app.patch("/orders/{order_id}/cancel")
async def cancel_order(order_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    if order.client_id != current_user.id and current_user.id != order.freelancer_id:
        raise HTTPException(status_code=403, detail="Only order participants can cancel order")
    
    if order.status not in ["open", "in_progress"]:
        raise HTTPException(status_code=400, detail="Order cannot be cancelled")
    
    order.status = "cancelled"
    
    # Уведомляем второго участника
    if current_user.id == order.client_id and order.freelancer_id:
        create_notification(
            db,
            order.freelancer_id,
            "Заказ отменен",
            f"Заказ '{order.title}' был отменен заказчиком",
            "order_cancelled",
            order.id
        )
    elif current_user.id == order.freelancer_id:
        create_notification(
            db,
            order.client_id,
            "Заказ отменен",
            f"Заказ '{order.title}' был отменен исполнителем",
            "order_cancelled",
            order.id
        )
    
    db.commit()
    return {"message": "Order cancelled successfully", "order_id": order_id}

# Получение сообщений чата
@app.get("/orders/{order_id}/messages")
async def get_chat_messages(
    order_id: int, 
    current_user: models.User = Depends(get_current_user), 
    db: Session = Depends(get_db)
):
    try:
        order = db.query(models.Order).filter(models.Order.id == order_id).first()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        
        if current_user.id not in [order.client_id, order.freelancer_id]:
            raise HTTPException(status_code=403, detail="Not authorized")
        
        messages = db.query(models.ChatMessage).filter(
            models.ChatMessage.order_id == order_id
        ).order_by(models.ChatMessage.created_at).all()
        
        return [
            {
                "id": msg.id,
                "sender_id": msg.sender_id,
                "sender_name": msg.sender.full_name,
                "message": msg.message,
                "is_own": msg.sender_id == current_user.id,
                "created_at": msg.created_at,
                "message_type": msg.message_type
            }
            for msg in messages
        ]
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in get_chat_messages: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Internal server error")

# Отправка сообщения (REST)
@app.post("/orders/{order_id}/messages")
async def send_message(
    order_id: int,
    message_data: ChatMessageCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        print(f"📨 Sending message to order {order_id} from user {current_user.id}")
        
        order = db.query(models.Order).filter(models.Order.id == order_id).first()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        
        # Проверяем доступ пользователя к заказу
        if current_user.id not in [order.client_id, order.freelancer_id]:
            raise HTTPException(status_code=403, detail="Not authorized to send messages")
        
        # Проверяем, что сообщение не пустое
        if not message_data.message or not message_data.message.strip():
            raise HTTPException(status_code=400, detail="Message cannot be empty")
        
        # Создаем сообщение
        message = models.ChatMessage(
            order_id=order_id,
            sender_id=current_user.id,
            message=message_data.message.strip(),
            message_type=message_data.message_type
        )
        
        db.add(message)
        db.commit()
        db.refresh(message)
        
        print(f"✅ Message saved: ID {message.id}, length: {len(message.message)}")
        
        # Уведомление получателю через WebSocket
        receiver_id = None
        if order.client_id == current_user.id and order.freelancer_id:
            receiver_id = order.freelancer_id
        elif order.freelancer_id == current_user.id:
            receiver_id = order.client_id
            
        if receiver_id:
            create_notification(
                db,
                receiver_id,
                "Новое сообщение",
                f"Новое сообщение в заказе '{order.title}'",
                "message",
                order_id
            )
        
        db.commit()
        
        # Формируем ответ
        response = {
            "id": message.id,
            "message": message.message,
            "created_at": message.created_at.isoformat(),
            "sender_id": message.sender_id,
            "order_id": message.order_id,
            "message_type": message.message_type
        }
        
        print(f"📤 Sending response: {response}")
        return response
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f"❌ Error in send_message: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Internal server error")

# Получение рейтинга пользователя
@app.get("/users/{user_id}/rating")
async def get_user_rating(user_id: int, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Получаем все отзывы пользователя
    reviews = db.query(models.Review).filter(
        models.Review.reviewed_user_id == user_id
    ).all()
    
    total_rating = sum(r.rating for r in reviews)
    review_count = len(reviews)
    avg_rating = total_rating / review_count if review_count > 0 else 0
    
    return {
        "rating": avg_rating,
        "review_count": review_count,
        "pro_eligible": avg_rating >= 4.5 and review_count >= 10,
        "level": "PRO" if avg_rating >= 4.5 else "Standard",
    }

# Активация PRO статуса
@app.patch("/users/pro")
async def update_pro_status(
    subscription_type: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # В реальном приложении здесь была бы интеграция с платежной системой
    current_user.is_pro = True
    current_user.pro_expires_at = datetime.utcnow() + timedelta(days=30)  # 30 дней для примера
    current_user.pro_subscription_type = subscription_type
    
    db.commit()
    
    return {
        "message": "PRO статус активирован",
        "expires_at": current_user.pro_expires_at,
        "subscription_type": subscription_type
    }

# Продвижение заказа
@app.patch("/orders/{order_id}/promote")
async def promote_order(
    order_id: int,
    promotion_type: str = "urgent",
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    if order.client_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # В реальном приложении здесь была бы проверка оплаты
    order.is_promoted = True
    order.promotion_type = promotion_type
    order.promoted_until = datetime.utcnow() + timedelta(days=1)  # 24 часа продвижения
    
    db.commit()
    
    return {
        "message": f"Заказ продвинут как {promotion_type}",
        "promoted_until": order.promoted_until,
        "promotion_type": promotion_type
    }

# Получение шаблонов заказов
@app.get("/templates")
async def get_templates(db: Session = Depends(get_db)):
    templates = [
        {
            "id": 1,
            "name": "Дизайн логотипа",
            "category": "Дизайн",
            "template": "Требования к логотипу:\n\n1. Стиль и концепция:\n   • Минимализм, современный стиль\n   • Векторный формат\n   • Адаптивный дизайн\n\n2. Цветовая палитра:\n   • Основной цвет: #[цвет1]\n   • Дополнительный: #[цвет2]\n   • Акцентный: #[цвет3]\n\n3. Сроки:\n   • Срок выполнения: [дней] дней\n   • Правки: 3 раунда\n\nБюджет: [сумма] ₽"
        },
        {
            "id": 2,
            "name": "Разработка сайта",
            "category": "Разработка",
            "template": "Техническое задание на разработку сайта:\n\n1. Тип сайта: [тип]\n2. Целевая аудитория: [описание]\n3. Основные цели: [цели]\n\n4. Функциональные требования:\n   • Адаптивная верстка\n   • CMS\n   • Форма обратной связи\n   • SEO-оптимизация\n\n5. Сроки и бюджет:\n   • Срок разработки: [дней] дней\n   • Бюджет: [сумма] ₽"
        },
        {
            "id": 3,
            "name": "Копирайтинг статьи",
            "category": "Копирайтинг",
            "template": "Требования к статье:\n\n1. Тема: [тема]\n2. Цель: [цель]\n3. Целевая аудитория: [ЦА]\n\n4. Технические требования:\n   • Объем: [символов]\n   • Уникальность: 95%+\n   • Ключевые слова: [слова]\n\n5. Сроки и оплата:\n   • Срок выполнения: [дней] дней\n   • Оплата: [сумма] ₽"
        }
    ]
    return templates

# Создание продвинутого заказа
@app.post("/orders/promoted")
async def create_promoted_order(
    order: OrderCreate,
    is_urgent: bool = False,
    is_premium: bool = False,
    placement_type: str = "urgent",
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.is_freelancer:
        raise HTTPException(status_code=400, detail="Freelancers cannot create orders")
    
    db_order = models.Order(
        title=order.title,
        description=order.description,
        requirements=order.requirements,
        budget=order.budget,
        client_id=current_user.id,
        deadline=order.deadline,
        category=order.category,
        is_urgent=is_urgent,
        is_premium=is_premium,
        placement_type=placement_type
    )
    
    db.add(db_order)
    
    # Уведомления для фрилансеров
    freelancers = db.query(models.User).filter(
        models.User.is_freelancer == True,
        models.User.is_active == True
    ).limit(50).all()  # Увеличили лимит для продвинутых заказов
    
    for freelancer in freelancers:
        create_notification(
            db,
            freelancer.id,
            "🔥 Премиум заказ доступен!",
            f"Новый {placement_type} заказ: '{order.title}' за {order.budget} руб.",
            "new_order_premium",
            db_order.id
        )
    
    db.commit()
    db.refresh(db_order)
    
    return db_order

# Получение срочных заказов
@app.get("/orders/urgent")
async def get_urgent_orders(
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db)
):
    # Получаем заказы, у которых дедлайн меньше чем через 24 часа
    twenty_four_hours_from_now = datetime.utcnow() + timedelta(hours=24)
    
    orders = db.query(models.Order).filter(
        models.Order.status == "open",
        models.Order.deadline <= twenty_four_hours_from_now,
        models.Order.deadline > datetime.utcnow()  # Только будущие дедлайны
    ).order_by(models.Order.deadline.asc()).offset(skip).limit(limit).all()
    
    return orders

# Создание отзыва
@app.post("/reviews")
async def create_review(
    review: ReviewCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    order = db.query(models.Order).filter(models.Order.id == review.order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    if order.status != "completed":
        raise HTTPException(status_code=400, detail="Can only review completed orders")
    
    if current_user.id not in [order.client_id, order.freelancer_id]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    reviewed_user_id = order.freelancer_id if current_user.id == order.client_id else order.client_id
    
    existing_review = db.query(models.Review).filter(
        models.Review.order_id == review.order_id,
        models.Review.reviewer_id == current_user.id
    ).first()
    
    if existing_review:
        raise HTTPException(status_code=400, detail="Already reviewed")
    
    if not 1 <= review.rating <= 5:
        raise HTTPException(status_code=400, detail="Rating must be between 1 and 5")
    
    db_review = models.Review(
        order_id=review.order_id,
        reviewer_id=current_user.id,
        reviewed_user_id=reviewed_user_id,
        rating=review.rating,
        comment=review.comment
    )
    
    db.add(db_review)
    
    # Обновляем рейтинг пользователя
    reviewed_user = db.query(models.User).filter(models.User.id == reviewed_user_id).first()
    if reviewed_user:
        all_reviews = db.query(models.Review).filter(
            models.Review.reviewed_user_id == reviewed_user_id
        ).all()
        
        total_rating = sum(r.rating for r in all_reviews) + review.rating
        review_count = len(all_reviews) + 1
        reviewed_user.rating = total_rating / review_count
        reviewed_user.review_count = review_count
    
    db.commit()
    db.refresh(db_review)
    
    return {
        "id": db_review.id,
        "rating": db_review.rating,
        "comment": db_review.comment,
        "created_at": db_review.created_at
    }

# Получение отзывов пользователя (с пагинацией)
@app.get("/users/{user_id}/reviews")
async def get_user_reviews(
    user_id: int, 
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db)
):
    try:
        skip = (page - 1) * limit
        
        reviews = db.query(models.Review).filter(
            models.Review.reviewed_user_id == user_id
        ).order_by(models.Review.created_at.desc()).offset(skip).limit(limit).all()
        
        return [
            {
                "id": r.id,
                "rating": r.rating,
                "comment": r.comment,
                "reply": r.reply,
                "reviewer_name": r.reviewer.full_name,
                "reviewer_id": r.reviewer_id,
                "order_title": r.order.title,
                "order_id": r.order_id,
                "created_at": r.created_at,
                "updated_at": r.updated_at
            }
            for r in reviews
        ]
        
    except Exception as e:
        print(f"Error getting user reviews: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

# Добавление ответа на отзыв (для исполнителя)
@app.post("/reviews/{review_id}/reply")
async def add_review_reply(
    review_id: int,
    reply_text: str = Query(..., min_length=1),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        review = db.query(models.Review).filter(models.Review.id == review_id).first()
        if not review:
            raise HTTPException(status_code=404, detail="Review not found")
        
        if review.reviewed_user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not authorized to reply")
        
        review.reply = reply_text
        review.updated_at = datetime.utcnow()
        
        db.commit()
        
        return {
            "message": "Reply added successfully",
            "review_id": review_id,
            "reply": reply_text
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error adding review reply: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

# Получение статистики отзывов
@app.get("/users/{user_id}/reviews/stats")
async def get_review_stats(user_id: int, db: Session = Depends(get_db)):
    try:
        reviews = db.query(models.Review).filter(
            models.Review.reviewed_user_id == user_id
        ).all()
        
        if not reviews:
            return {
                "total_reviews": 0,
                "average_rating": 0,
                "rating_distribution": {1: 0, 2: 0, 3: 0, 4: 0, 5: 0},
                "recent_reviews": []
            }
        
        total_reviews = len(reviews)
        average_rating = sum(r.rating for r in reviews) / total_reviews
        
        # Распределение по звездам
        rating_distribution = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        for review in reviews:
            rating_distribution[review.rating] += 1
        
        # Последние 5 отзывов
        recent_reviews = [
            {
                "rating": r.rating,
                "comment": r.comment[:100] + "..." if r.comment and len(r.comment) > 100 else r.comment,
                "created_at": r.created_at
            }
            for r in sorted(reviews, key=lambda x: x.created_at, reverse=True)[:5]
        ]
        
        return {
            "total_reviews": total_reviews,
            "average_rating": round(average_rating, 1),
            "rating_distribution": rating_distribution,
            "recent_reviews": recent_reviews
        }
        
    except Exception as e:
        print(f"Error getting review stats: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

# Получение уведомлений пользователя
@app.get("/notifications", response_model=List[NotificationResponse])
async def get_notifications(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    notifications = db.query(models.Notification).filter(
        models.Notification.user_id == current_user.id
    ).order_by(models.Notification.created_at.desc()).limit(50).all()
    
    return notifications

# Получение количества непрочитанных уведомлений
@app.get("/notifications/unread-count")
async def get_unread_notifications_count(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        count = db.query(models.Notification).filter(
            models.Notification.user_id == current_user.id,
            models.Notification.is_read == False
        ).count()
        
        return {"count": count}
    except Exception as e:
        print(f"Error in get_unread_notifications_count: {e}")
        return {"count": 0}

# Отметить уведомление как прочитанное
@app.patch("/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    notification = db.query(models.Notification).filter(
        models.Notification.id == notification_id,
        models.Notification.user_id == current_user.id
    ).first()
    
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    
    notification.is_read = True
    db.commit()
    
    return {"message": "Notification marked as read"}

# Отметить все уведомления как прочитанные
@app.patch("/notifications/read-all")
async def mark_all_notifications_read(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    notifications = db.query(models.Notification).filter(
        models.Notification.user_id == current_user.id,
        models.Notification.is_read == False
    ).all()
    
    for notification in notifications:
        notification.is_read = True
    
    db.commit()
    
    return {"message": f"{len(notifications)} notifications marked as read"}

# Получение информации о текущем пользователе
@app.get("/users/me", response_model=auth.UserResponse)
async def read_users_me(current_user: models.User = Depends(get_current_user)):
    return current_user

# Получение профиля пользователя
@app.get("/users/{user_id}")
async def get_user_profile(user_id: int, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    reviews = db.query(models.Review).filter(
        models.Review.reviewed_user_id == user_id
    ).all()
    
    completed_orders = db.query(models.Order).filter(
        models.Order.freelancer_id == user_id,
        models.Order.status == "completed"
    ).count() if user.is_freelancer else 0
    
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "is_freelancer": user.is_freelancer,
        "rating": user.rating,
        "review_count": user.review_count,
        "completed_orders": completed_orders,
        "created_at": user.created_at
    }

# Обновление профиля
@app.patch("/users/me")
async def update_profile(
    full_name: Optional[str] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if full_name:
        current_user.full_name = full_name
    
    db.commit()
    db.refresh(current_user)
    
    return current_user

# Тестовый эндпоинт
@app.get("/")
async def root():
    return {"message": "Добро пожаловать в API ВРаботе!", "status": "online", "version": "2.0.0"}

# Статистика
@app.get("/stats")
async def get_stats(current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        if current_user.is_freelancer:
            total_bids = db.query(models.Bid).filter(
                models.Bid.freelancer_id == current_user.id
            ).count()
            
            accepted_bids = db.query(models.Bid).filter(
                models.Bid.freelancer_id == current_user.id,
                models.Bid.status == "accepted"
            ).count()
            
            completed_orders = db.query(models.Order).filter(
                models.Order.freelancer_id == current_user.id,
                models.Order.status == "completed"
            ).count()
            
            total_earnings = db.query(models.Order).filter(
                models.Order.freelancer_id == current_user.id,
                models.Order.status == "completed"
            ).with_entities(func.sum(models.Order.budget)).scalar() or 0
            
            return {
                "total_bids": total_bids,
                "accepted_bids": accepted_bids,
                "completed_orders": completed_orders,
                "total_earnings": total_earnings,
                "rating": current_user.rating,
                "review_count": current_user.review_count
            }
        else:
            total_orders = db.query(models.Order).filter(
                models.Order.client_id == current_user.id,
                models.Order.status != 'cancelled'  # ИСКЛЮЧАЕМ отмененные!
            ).count()
            
            completed_orders = db.query(models.Order).filter(
                models.Order.client_id == current_user.id,
                models.Order.status == "completed"
            ).count()
            
            total_spent_result = db.query(func.sum(models.Order.budget)).filter(
                models.Order.client_id == current_user.id,
                models.Order.status == 'completed'
            ).scalar()
            total_spent = total_spent_result or 0
            
            return {
                "total_orders": total_orders,
                "completed_orders": completed_orders,
                "total_spent": total_spent
            }
    except Exception as e:
        print(f"Error in get_stats: {e}")
        import traceback
        traceback.print_exc()
        # Возвращаем дефолтные значения при ошибке
        return {
            "total_orders": 0,
            "completed_orders": 0,
            "total_spent": 0,
            "total_earnings": 0,
            "accepted_bids": 0,
            "rating": 0
        }

# Поиск заказов
@app.get("/orders/search")
async def search_orders(
    q: Optional[str] = Query(None),
    min_budget: Optional[float] = Query(None),
    max_budget: Optional[float] = Query(None),
    category: Optional[str] = Query(None),
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    try:
        # Для фрилансеров показываем только открытые заказы
        if current_user.is_freelancer:
            query = db.query(models.Order).filter(models.Order.status == "open")
        else:
            # Для клиентов показываем их заказы
            query = db.query(models.Order).filter(models.Order.client_id == current_user.id)
        
        if q:
            query = query.filter(
                or_(
                    models.Order.title.ilike(f"%{q}%"),
                    models.Order.description.ilike(f"%{q}%")
                )
            )
        
        if min_budget:
            query = query.filter(models.Order.budget >= min_budget)
        
        if max_budget:
            query = query.filter(models.Order.budget <= max_budget)
        
        if category:
            query = query.filter(models.Order.category == category)
        
        orders = query.order_by(models.Order.created_at.desc()).offset(skip).limit(limit).all()
        return orders
        
    except Exception as e:
        print(f"Error in search_orders: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Internal server error")

# Получение категорий заказов
@app.get("/orders/categories")
async def get_categories(db: Session = Depends(get_db)):
    """
    Возвращает список уникальных категорий из таблицы заказов.
    """
    try:
        # ПРАВИЛЬНЫЙ запрос: выбираем значение категории
        categories = db.query(models.Order.category).filter(
            models.Order.category.isnot(None),
            models.Order.category != ''
        ).distinct().all()
        
        # Преобразуем список кортежей в список строк
        category_list = [category for (category,) in categories if category]
        
        # Если нет категорий, возвращаем дефолтные
        if not category_list:
            category_list = ['Дизайн', 'Разработка', 'Копирайтинг', 'Маркетинг', 'Другое']
        
        print(f"📊 Категории отправлены: {category_list}")
        return category_list
        
    except Exception as e:
        print(f"❌ Ошибка в /orders/categories: {e}")
        import traceback
        traceback.print_exc()
        return ['Дизайн', 'Разработка', 'Копирайтинг', 'Маркетинг', 'Другое']

# Запуск приложения
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)