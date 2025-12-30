from typing import Dict, Set
from fastapi import WebSocket
import json

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
        print(f"✅ User {user_id} connected to room {room_id}")

    def disconnect(self, user_id: int, room_id: str):
        if user_id in self.active_connections:
            del self.active_connections[user_id]
        if user_id in self.user_rooms and room_id in self.user_rooms[user_id]:
            self.user_rooms[user_id].remove(room_id)
        print(f"❌ User {user_id} disconnected from room {room_id}")

    async def send_personal_message(self, message: dict, user_id: int):
        if user_id in self.active_connections:
            try:
                await self.active_connections[user_id].send_json(message)
            except Exception as e:
                print(f"Error sending to user {user_id}: {e}")

    async def broadcast_to_room(self, message: dict, room_id: str, exclude_user_id: int = None):
        for user_id, rooms in self.user_rooms.items():
            if room_id in rooms and user_id != exclude_user_id:
                await self.send_personal_message(message, user_id)

manager = ConnectionManager()