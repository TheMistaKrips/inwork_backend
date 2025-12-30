import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy.orm import Session
from database import engine, SessionLocal, Base
import models
import auth

def init_database():
    """Инициализация базы данных с тестовыми данными"""
    
    print("🔄 Создание таблиц базы данных...")
    
    # Удаляем старые таблицы и создаем новые
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    
    try:
        print("👥 Создание тестовых пользователей...")
        
        # Создаем тестового клиента
        hashed_password = auth.get_password_hash("test123")
        test_client = models.User(
            email="test@test.ru",
            full_name="Тест Клиент",
            hashed_password=hashed_password,
            is_freelancer=False
        )
        db.add(test_client)
        
        # Создаем тестового фрилансера
        hashed_password_freelancer = auth.get_password_hash("test123")
        test_freelancer = models.User(
            email="freelancer@test.ru",
            full_name="Тест Фрилансер",
            hashed_password=hashed_password_freelancer,
            is_freelancer=True
        )
        db.add(test_freelancer)
        
        db.commit()
        db.refresh(test_client)
        db.refresh(test_freelancer)
        
        print(f"✅ Тестовый клиент: {test_client.email} / test123")
        print(f"✅ Тестовый фрилансер: {test_freelancer.email} / test123")
        
        # Создаем тестовые заказы
        from datetime import datetime, timedelta
        
        print("📦 Создание тестовых заказов...")
        
        orders_data = [
            {
                "title": "Разработка логотипа для IT компании",
                "description": "Требуется создать современный минималистичный логотип для стартапа в сфере искусственного интеллекта.",
                "requirements": "Векторный формат (AI, SVG), минималистичный дизайн, цветовая гамма: синие/голубые тона",
                "budget": 5000.0,
                "client_id": test_client.id,
                "deadline": datetime.utcnow() + timedelta(days=7)
            },
            {
                "title": "Написание статьи про веб-разработку",
                "description": "Нужна информативная статья о современных фреймворках для фронтенд разработки на 2024 год.",
                "requirements": "Объем: 3000-3500 слов, уникальность: 95%+, SEO-оптимизация",
                "budget": 3000.0,
                "client_id": test_client.id,
                "deadline": datetime.utcnow() + timedelta(days=5)
            },
        ]
        
        for order_data in orders_data:
            order = models.Order(**order_data)
            db.add(order)
        
        db.commit()
        
        print("✅ База данных успешно инициализирована!")
        print("\n📋 Тестовые данные:")
        print("1. Клиент: test@test.ru / test123")
        print("2. Фрилансер: freelancer@test.ru / test123")
        print("3. Создано 2 тестовых заказа")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    init_database()