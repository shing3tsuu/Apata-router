import json
import logging
import asyncio
from typing import Dict, List
from fastapi import WebSocket, WebSocketDisconnect


class WebSocketManager:
    def __init__(self, redis_client, logger: logging.Logger):
        self._redis = redis_client
        self._logger = logger
        self.active_connections: dict[int, WebSocket] = {}
        self._should_listen = True

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[user_id] = websocket
        self._logger.info(f"User {user_id} connected. Active connections: {len(self.active_connections)}")

    async def disconnect(self, user_id: int):
        if user_id in self.active_connections:
            del self.active_connections[user_id]
            self._logger.info(f"User {user_id} disconnected. Active connections: {len(self.active_connections)}")

    async def send_personal_message(self, message: dict, user_id: int) -> bool:
        if user_id in self.active_connections:
            try:
                await self.active_connections[user_id].send_json(message)
                return True
            except Exception as e:
                self._logger.error(f"Error sending message to user {user_id}: {e}")
                await self.disconnect(user_id)
                return False
        return False

    async def broadcast_to_contacts(self, message: dict, contact_ids: list[int]):
        """Send message to multiple contacts"""
        sent_count = 0
        for contact_id in contact_ids:
            if await self.send_personal_message(message, contact_id):
                sent_count += 1
        self._logger.info(f"Broadcasted message to {sent_count}/{len(contact_ids)} contacts")

    async def broadcast_user_status(self, user_id: int, online: bool, contact_ids: list[int]):
        """Broadcast user status to their contacts"""
        try:
            status_message = {
                "type": "user_status",
                "user_id": user_id,
                "online": online,
                "timestamp": asyncio.get_event_loop().time()
            }

            # Send to contacts via WebSocket
            await self.broadcast_to_contacts(status_message, contact_ids)

            # Also publish to Redis for other instances
            self._redis.publish("user_status_updates", json.dumps({
                **status_message,
                "contact_ids": contact_ids
            }))

            self._logger.info(f"User {user_id} status updated: online={online}, notified {len(contact_ids)} contacts")
        except Exception as e:
            self._logger.error(f"Error broadcasting user status: {e}")

    async def start_redis_listener(self):
        try:
            pubsub = self._redis.pubsub()
            pubsub.subscribe("new_messages", "user_status_updates")

            while self._should_listen:
                try:
                    message = pubsub.get_message(timeout=1.0)
                    if message and message['type'] == 'message':
                        try:
                            data = json.loads(message['data'])
                            channel = message['channel'].decode()

                            if channel == "new_messages":
                                recipient_id = data['recipient_id']
                                success = await self.send_personal_message(data, recipient_id)
                                if success:
                                    self._logger.info(f"Message delivered via Redis to user {recipient_id}")
                                else:
                                    self._logger.info(f"User {recipient_id} is offline, message remains undelivered")

                            elif channel == "user_status_updates":
                                # Forward status updates to connected clients
                                user_id = data['user_id']
                                online = data['online']
                                contact_ids = data.get('contact_ids', [])

                                status_message = {
                                    "type": "user_status",
                                    "user_id": user_id,
                                    "online": online,
                                    "timestamp": data['timestamp']
                                }

                                await self.broadcast_to_contacts(status_message, contact_ids)
                                self._logger.info(
                                    f"Status update forwarded for user {user_id} to {len(contact_ids)} contacts")

                        except Exception as e:
                            self._logger.error(f"Error processing Redis message: {e}")

                    await asyncio.sleep(0.1)

                except Exception as e:
                    self._logger.error(f"Redis listener error: {e}")
                    await asyncio.sleep(1)
        except Exception as e:
            self._logger.error(f"Redis listener setup error: {e}")

    async def stop_redis_listener(self):
        self._should_listen = False