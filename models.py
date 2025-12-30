from sqlalchemy import Column, Integer, String, Float, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    is_freelancer = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    rating = Column(Float, default=0.0)
    review_count = Column(Integer, default=0)
    
    # Отношения
    orders_created = relationship("Order", 
                                 foreign_keys="Order.client_id",
                                 back_populates="client",
                                 lazy="dynamic")
    
    bids = relationship("Bid", 
                       back_populates="freelancer",
                       lazy="dynamic")
    
    # Добавляем обратные связи
    notifications = relationship("Notification", 
                                back_populates="user",
                                lazy="dynamic")
    
    sent_messages = relationship("ChatMessage", 
                                foreign_keys="ChatMessage.sender_id",
                                back_populates="sender",
                                lazy="dynamic")
    
    given_reviews = relationship("Review", 
                                foreign_keys="Review.reviewer_id",
                                back_populates="reviewer",
                                lazy="dynamic")
    
    received_reviews = relationship("Review", 
                                   foreign_keys="Review.reviewed_user_id",
                                   back_populates="reviewed_user",
                                   lazy="dynamic")

class Order(Base):
    __tablename__ = "orders"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    requirements = Column(Text)
    budget = Column(Float)
    client_id = Column(Integer, ForeignKey("users.id"))
    freelancer_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(String, default="open")  # open, in_progress, completed, cancelled
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    deadline = Column(DateTime(timezone=True), nullable=True)
    category = Column(String, default="other")
    
    # Отношения
    client = relationship("User", 
                         foreign_keys=[client_id],
                         back_populates="orders_created")
    
    assigned_freelancer = relationship("User", 
                                      foreign_keys=[freelancer_id])
    
    bids = relationship("Bid", 
                       back_populates="order",
                       lazy="dynamic",
                       cascade="all, delete-orphan")
    
    messages = relationship("ChatMessage", 
                           back_populates="order",
                           lazy="dynamic",
                           cascade="all, delete-orphan")
    
    reviews = relationship("Review", 
                          back_populates="order",
                          lazy="dynamic",
                          cascade="all, delete-orphan")

class Bid(Base):
    __tablename__ = "bids"
    
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"))
    freelancer_id = Column(Integer, ForeignKey("users.id"))
    amount = Column(Float)
    proposal = Column(Text)
    portfolio_links = Column(Text, nullable=True)
    status = Column(String, default="pending")  # pending, accepted, rejected
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Отношения
    order = relationship("Order", back_populates="bids")
    freelancer = relationship("User", back_populates="bids")
    
class ChatMessage(Base):
    __tablename__ = "chat_messages"
    
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    message = Column(Text, nullable=False)
    message_type = Column(String, default="text")
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Исправленные отношения
    order = relationship("Order", back_populates="messages")
    sender = relationship("User", 
                         foreign_keys=[sender_id],
                         back_populates="sent_messages")


class Notification(Base):
    __tablename__ = "notifications"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    notification_type = Column(String)
    related_id = Column(Integer)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Исправленное отношение
    user = relationship("User", 
                       foreign_keys=[user_id],
                       back_populates="notifications")

class Review(Base):
    __tablename__ = "reviews"
    
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    reviewer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    reviewed_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    rating = Column(Integer, nullable=False)
    comment = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Исправленные отношения
    order = relationship("Order", 
                        foreign_keys=[order_id],
                        back_populates="reviews")
    
    reviewer = relationship("User", 
                          foreign_keys=[reviewer_id],
                          back_populates="given_reviews")
    
    reviewed_user = relationship("User", 
                               foreign_keys=[reviewed_user_id],
                               back_populates="received_reviews")