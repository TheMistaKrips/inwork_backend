# backend/test_api.py
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import pytest
import requests
from datetime import datetime, timedelta

BASE_URL = "http://localhost:8000"

# === 1. ФИКСТУРЫ (TEST DATA) ===
@pytest.fixture
def test_user_client():
    """Данные тестового клиента."""
    return {"email": f"test_client_{datetime.now().timestamp()}@test.ru", "password": "test123", "full_name": "Test Client"}

@pytest.fixture
def test_user_freelancer():
    """Данные тестового фрилансера."""
    return {"email": f"test_freelancer_{datetime.now().timestamp()}@test.ru", "password": "test123", "full_name": "Test Freelancer", "is_freelancer": True}

# === 2. ТЕСТЫ АВТОРИЗАЦИИ ===
class TestAuth:
    def test_register_client(self, test_user_client):
        """Тест регистрации нового клиента."""
        response = requests.post(f"{BASE_URL}/register", json=test_user_client)
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == test_user_client["email"]
        assert "id" in data
        print(f"✅ Клиент зарегистрирован: {data['email']}")

    def test_login_and_get_token(self, test_user_client):
        """Тест входа в систему и получения JWT токена."""
        # 1. Сначала регистрируем
        reg_response = requests.post(f"{BASE_URL}/register", json=test_user_client)
        # 2. Пытаемся войти (OAuth2 password flow)
        form_data = {
            'username': test_user_client['email'],
            'password': test_user_client['password']
        }
        login_response = requests.post(f"{BASE_URL}/token", data=form_data)
        assert login_response.status_code == 200
        token_data = login_response.json()
        assert "access_token" in token_data
        assert token_data["token_type"] == "bearer"
        print(f"✅ Логин успешен, токен получен")

# === 3. ТЕСТЫ ЗАКАЗОВ (ПОЛНЫЙ ЦИКЛ) ===
class TestOrderFullCycle:
    @pytest.fixture(autouse=True)
    def setup(self, test_user_client, test_user_freelancer):
        """Фикстура для создания пользователей и получения их токенов перед каждым тестом цикла."""
        # Регистрируем и логиним клиента
        requests.post(f"{BASE_URL}/register", json=test_user_client)
        client_login = requests.post(f"{BASE_URL}/token", data={'username': test_user_client['email'], 'password': test_user_client['password']})
        self.client_token = client_login.json()["access_token"]
        self.client_headers = {"Authorization": f"Bearer {self.client_token}"}

        # Регистрируем и логиним фрилансера
        requests.post(f"{BASE_URL}/register", json=test_user_freelancer)
        freelancer_login = requests.post(f"{BASE_URL}/token", data={'username': test_user_freelancer['email'], 'password': test_user_freelancer['password']})
        self.freelancer_token = freelancer_login.json()["access_token"]
        self.freelancer_headers = {"Authorization": f"Bearer {self.freelancer_token}"}

        self.order_id = None
        self.bid_id = None
        yield

    def test_1_create_order_by_client(self):
        """Клиент создает заказ."""
        order_data = {
            "title": "Тестовый заказ на разработку логотипа",
            "description": "Нужно нарисовать логотип для стартапа",
            "requirements": "Минимализм, векторный формат",
            "budget": 5000.0,
            "deadline": (datetime.utcnow() + timedelta(days=7)).isoformat() + "Z",
            "category": "Дизайн"
        }
        response = requests.post(f"{BASE_URL}/orders", json=order_data, headers=self.client_headers)
        assert response.status_code == 200
        order = response.json()
        assert order["title"] == order_data["title"]
        assert order["status"] == "open"
        self.order_id = order["id"]
        print(f"✅ Заказ создан, ID: {self.order_id}")

    def test_2_freelancer_creates_bid(self):
        """Фрилансер видит заказ и отправляет отклик (бид)."""
        # Сначала создаем заказ, если его еще нет
        if not self.order_id:
            self.test_1_create_order_by_client()

        bid_data = {
            "order_id": self.order_id,
            "amount": 4500.0,
            "proposal": "Я выполню ваш логотип за 5 дней, вот мое портфолио...",
            "portfolio_links": "https://myportfolio.com/example1, https://github.com/mywork"
        }
        response = requests.post(f"{BASE_URL}/bids", json=bid_data, headers=self.freelancer_headers)
        assert response.status_code == 200
        bid = response.json()
        assert bid["amount"] == bid_data["amount"]
        self.bid_id = bid["id"]
        print(f"✅ Отклик создан, ID: {self.bid_id}")

    def test_3_client_accepts_bid(self):
        """Клиент принимает отклик фрилансера."""
        # Создаем заказ и отклик, если их нет
        if not self.bid_id:
            self.test_2_freelancer_creates_bid()

        response = requests.patch(f"{BASE_URL}/bids/{self.bid_id}/accept", headers=self.client_headers)
        assert response.status_code == 200
        # Проверяем, что статус заказа изменился
        order_response = requests.get(f"{BASE_URL}/orders/{self.order_id}", headers=self.client_headers)
        order = order_response.json()
        assert order["status"] == "in_progress"
        assert order["freelancer_id"] is not None
        print(f"✅ Отклик принят, заказ в работе")

    def test_4_send_chat_message(self):
        """Участники заказа обмениваются сообщениями в чате."""
        if not self.order_id:
            self.test_1_create_order_by_client()

        # Клиент отправляет сообщение
        message_data = {"message": "Здравствуйте! Когда сможете начать?", "message_type": "text"}
        response = requests.post(f"{BASE_URL}/orders/{self.order_id}/messages", json=message_data, headers=self.client_headers)
        assert response.status_code == 200
        print("✅ Сообщение в чат отправлено")

    def test_5_client_completes_order(self):
        """Клиент завершает заказ."""
        # 1. Создаем заказ, если его еще нет
        if not self.order_id:
            self.test_1_create_order_by_client()
        
        # 2. Создаем отклик, если его еще нет
        if not self.bid_id:
            self.test_2_freelancer_creates_bid()
        
        # 3. Принимаем отклик, если он еще не принят
        # Проверяем статус заказа
        order_response = requests.get(f"{BASE_URL}/orders/{self.order_id}", headers=self.client_headers)
        current_order = order_response.json()
        
        if current_order["status"] != "in_progress":
            # Принимаем отклик
            print(f"🔄 Принимаем отклик {self.bid_id} для заказа {self.order_id}")
            accept_response = requests.patch(f"{BASE_URL}/bids/{self.bid_id}/accept", headers=self.client_headers)
            assert accept_response.status_code == 200, f"Не удалось принять отклик: {accept_response.text}"
            
            # Даем время на обновление статуса
            import time
            time.sleep(0.5)
        
        # 4. Теперь завершаем заказ
        print(f"✅ Завершаем заказ {self.order_id}")
        response = requests.patch(f"{BASE_URL}/orders/{self.order_id}/complete", headers=self.client_headers)
        
        print(f"Status Code: {response.status_code}")
        print(f"Response Text: {response.text}")
        
        assert response.status_code == 200, f"Не удалось завершить заказ: {response.text}"
        
        # 5. Проверяем финальный статус
        order_response = requests.get(f"{BASE_URL}/orders/{self.order_id}", headers=self.client_headers)
        order = order_response.json()
        assert order["status"] == "completed", f"Ожидался статус 'completed', получен '{order['status']}'"
        print(f"✅ Заказ успешно завершен")

# === ЗАПУСК ВСЕХ ТЕСТОВ ===
if __name__ == "__main__":
    # Запуск с детальным выводом и игнорированием предупреждек
    pytest.main(["-v", "-s", "--tb=short", "-W", "ignore::DeprecationWarning"])