import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session
from database import engine, SessionLocal
import models
import auth
from datetime import datetime, timedelta

def create_test_data():
    db = SessionLocal()
    
    try:
        # Удаляем старые данные (опционально)
        db.query(models.Bid).delete()
        db.query(models.Order).delete()
        db.query(models.User).delete()
        db.commit()
        
        print("Старые данные очищены")
        
        # Создаем тестового клиента
        hashed_password = auth.get_password_hash("test123")
        test_client = models.User(
            email="client@test.ru",
            full_name="Иван Клиентов",
            hashed_password=hashed_password,
            is_freelancer=False
        )
        db.add(test_client)
        
        # Создаем тестового фрилансера
        hashed_password_freelancer = auth.get_password_hash("test123")
        test_freelancer = models.User(
            email="freelancer@test.ru",
            full_name="Петр Фрилансеров",
            hashed_password=hashed_password_freelancer,
            is_freelancer=True
        )
        db.add(test_freelancer)
        
        db.commit()
        db.refresh(test_client)
        db.refresh(test_freelancer)
        
        print(f"Создан тестовый клиент: {test_client.email}")
        print(f"Создан тестовый фрилансер: {test_freelancer.email}")
        
        # Создаем тестовые заказы
        orders_data = [
            {
                "title": "Разработка логотипа для IT компании",
                "description": "Требуется создать современный минималистичный логотип для стартапа в сфере искусственного интеллекта. Логотип должен отражать технологичность и инновационность.",
                "requirements": "• Векторный формат (AI, SVG)\n• Минималистичный дизайн\n• Цветовая гамма: синие/голубые тона\n• Адаптивность под разные носители\n• Срок: 7 дней",
                "budget": 5000,
                "client_id": test_client.id,
                "deadline": datetime.utcnow() + timedelta(days=7)
            },
            {
                "title": "Написание статьи про веб-разработку",
                "description": "Нужна информативная статья о современных фреймворках для фронтенд разработки на 2024 год. Статья должна быть полезна как новичкам, так и опытным разработчикам.",
                "requirements": "• Объем: 3000-3500 слов\n• Уникальность: 95%+\n• SEO-оптимизация\n• Примеры кода\n• Список источников\n• Срок: 5 дней",
                "budget": 3000,
                "client_id": test_client.id,
                "deadline": datetime.utcnow() + timedelta(days=5)
            },
            {
                "title": "Верстка лендинга для онлайн-курса",
                "description": "Требуется сверстать продающую страницу для нового онлайн-курса по программированию. Лендинг должен быть современным, быстрым и конверсионным.",
                "requirements": "• Адаптивная верстка (мобильные, планшеты, десктоп)\n• Анимации на CSS/JS\n• Интеграция формы заявки\n• Оптимизация скорости загрузки\n• Кроссбраузерность\n• Срок: 10 дней",
                "budget": 8000,
                "client_id": test_client.id,
                "deadline": datetime.utcnow() + timedelta(days=10)
            },
            {
                "title": "Разработка Telegram бота для заказов",
                "description": "Нужен бот для автоматизации приема заказов в небольшом интернет-магазине. Бот должен принимать заказы, отправлять уведомления и формировать отчеты.",
                "requirements": "• Интеграция с базой данных\n• Система оплаты через ЮKassa\n• Админ-панель для управления\n• Уведомления в Telegram\n• Экспорт данных в Excel\n• Срок: 14 дней",
                "budget": 15000,
                "client_id": test_client.id,
                "deadline": datetime.utcnow() + timedelta(days=14)
            },
            {
                "title": "Дизайн мобильного приложения",
                "description": "Разработка UI/UX дизайна для мобильного приложения доставки еды. Приложение должно быть удобным, современным и соответствовать трендам 2024 года.",
                "requirements": "• Дизайн 10+ экранов\n• Прототипы в Figma\n• Руководство по стилю\n• Адаптация под iOS и Android\n• Анимации интерфейса\n• Срок: 12 дней",
                "budget": 12000,
                "client_id": test_client.id,
                "deadline": datetime.utcnow() + timedelta(days=12)
            }
        ]
        
        orders = []
        for order_data in orders_data:
            order = models.Order(**order_data)
            db.add(order)
            orders.append(order)
        
        db.commit()
        
        # Создаем тестовые отклики (биды)
        bids_data = [
            {
                "order_id": orders[0].id,
                "freelancer_id": test_freelancer.id,
                "amount": 4500,
                "proposal": "У меня большой опыт в дизайне логотипов для IT-компаний. Выполню работу за 5 дней, предоставлю 3 варианта на выбор.",
                "status": "pending"
            },
            {
                "order_id": orders[1].id,
                "freelancer_id": test_freelancer.id,
                "amount": 2500,
                "proposal": "Я технический писатель с 5-летним опытом. Напишу статью с реальными примерами и актуальными исследованиями.",
                "status": "accepted"
            },
            {
                "order_id": orders[2].id,
                "freelancer_id": test_freelancer.id,
                "amount": 7000,
                "proposal": "Верстаю современные лендинги с анимациями и высокой скоростью загрузки. Использую Tailwind CSS и GSAP.",
                "status": "pending"
            }
        ]
        
        for bid_data in bids_data:
            bid = models.Bid(**bid_data)
            db.add(bid)
        
        # Обновляем статус одного заказа (чтобы был принятый отклик)
        accepted_order = orders[1]
        accepted_order.freelancer_id = test_freelancer.id
        accepted_order.status = "in_progress"
        
        db.commit()
        
        print(f"Создано {len(orders)} тестовых заказов")
        print(f"Создано {len(bids_data)} тестовых откликов")
        print("\nТестовые аккаунты для входа:")
        print("Клиент: client@test.ru / test123")
        print("Фрилансер: freelancer@test.ru / test123")
        print("\nТестовые данные успешно созданы!")
        
    except Exception as e:
        print(f"Ошибка: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    # Создаем таблицы
    from database import Base
    Base.metadata.create_all(bind=engine)
    
    create_test_data()