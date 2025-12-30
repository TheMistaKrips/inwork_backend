import asyncio
import json
from datetime import datetime
from typing import Dict, Set
from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from database import SessionLocal
import models
import auth

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, WebSocket] = {}
        self.user_rooms: Dict[int, Set[str]] = {}

    async def connect(self, websocket: WebSocket, user_id: int, room_id: str):
        await websocket.accept()
        self.active_connections[user_id] = websocket
        if user_id not in self.user_rooms:
            self.user_rooms[user_id] = set()
        self.user_rooms[user_id].add(room_id)
        print(f"User {user_id} connected to room {room_id}")

    def disconnect(self, user_id: int, room_id: str):
        if user_id in self.active_connections:
            del self.active_connections[user_id]
        if user_id in self.user_rooms and room_id in self.user_rooms[user_id]:
            self.user_rooms[user_id].remove(room_id)
        print(f"User {user_id} disconnected from room {room_id}")

    async def send_personal_message(self, message: dict, user_id: int):
        if user_id in self.active_connections:
            try:
                await self.active_connections[user_id].send_json(message)
            except Exception as e:
                print(f"Error sending to user {user_id}: {e}")

    async def broadcast_to_room(self, message: dict, room_id: str, exclude_user_id: int = None):
        # Отправляем сообщение всем пользователям в комнате
        for user_id, rooms in self.user_rooms.items():
            if room_id in rooms and user_id != exclude_user_id:
                await self.send_personal_message(message, user_id)

manager = ConnectionManager()

async def websocket_endpoint(websocket: WebSocket, user_id: int, order_id: int):
    room_id = f"order_{order_id}"
    
    await manager.connect(websocket, user_id, room_id)
    
    try:
        while True:
            # Получаем сообщение от клиента
            data = await websocket.receive_text()
            message_data = json.loads(data)
            
            # Сохраняем сообщение в базу
            db = SessionLocal()
            try:
                message = models.ChatMessage(
                    order_id=order_id,
                    sender_id=user_id,
                    message=message_data["message"],
                    message_type=message_data.get("type", "text")
                )
                db.add(message)
                db.commit()
                db.refresh(message)
                
                # Формируем ответ для отправки
                response = {
                    "type": "message",
                    "id": message.id,
                    "order_id": order_id,
                    "sender_id": user_id,
                    "message": message.message,
                    "message_type": message.message_type,
                    "created_at": message.created_at.isoformat(),
                    "is_own": False  # Для получателя
                }
                
                # Отправляем всем в комнате кроме отправителя
                await manager.broadcast_to_room(response, room_id, user_id)
                
                # Отправляем подтверждение отправителю
                confirm_response = response.copy()
                confirm_response["is_own"] = True
                await manager.send_personal_message(confirm_response, user_id)
                
            except Exception as e:
                print(f"Error saving message: {e}")
            finally:
                db.close()
                
    except WebSocketDisconnect:
        manager.disconnect(user_id, room_id)
    except Exception as e:
        print(f"WebSocket error: {e}")
        manager.disconnect(user_id, room_id)