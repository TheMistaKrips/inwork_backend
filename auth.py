from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from pydantic import BaseModel
import hashlib
import base64
import os

# Конфигурация
SECRET_KEY = "your-secret-key-change-in-production-please-change-this"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    email: Optional[str] = None

class UserCreate(BaseModel):
    email: str
    password: str
    full_name: str
    is_freelancer: bool = False

class UserResponse(BaseModel):
    id: int
    email: str
    full_name: str
    is_freelancer: bool

    class Config:
        from_attributes = True

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Простая проверка пароля с солью"""
    try:
        # Разделяем хеш и соль
        if ":" not in hashed_password:
            return False
        
        salt, stored_hash = hashed_password.split(":")
        
        # Вычисляем хеш от пароля + соль
        computed_hash = hashlib.sha256((plain_password + salt).encode()).hexdigest()
        
        return computed_hash == stored_hash
    except:
        return False

def get_password_hash(password: str) -> str:
    """Генерация хеша пароля с солью"""
    # Генерируем случайную соль
    salt = base64.b64encode(os.urandom(16)).decode('utf-8')
    
    # Вычисляем хеш от пароля + соль
    password_hash = hashlib.sha256((password + salt).encode()).hexdigest()
    
    # Возвращаем в формате "соль:хеш"
    return f"{salt}:{password_hash}"

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt