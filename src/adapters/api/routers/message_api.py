import redis
import logging
import json
import asyncio
from datetime import datetime

from fastapi import APIRouter, HTTPException, status, Depends, Query, WebSocket, WebSocketDisconnect
from dishka.integrations.fastapi import inject
from dishka import FromDishka, AsyncContainer

from src.adapters.database.service import UserService, ContactService, MessageService
from src.adapters.database.dto import UserRequestDTO, MessageRequestDTO
from ..models.message_api_models import *
from .auth_api import AuthAPI
from .websocket_manager import WebSocketManager


class MessageAPI:
    def __init__(
            self,
            auth_api: AuthAPI,
            redis_client: redis.Redis,
            logger: logging.Logger,
    ):
        self._redis = redis_client
        self._logger = logger
        self._auth_api = auth_api
        self.ws_manager = WebSocketManager(self._redis, self._logger)
        self._redis_listener_task = None
        self._message_router = APIRouter(tags=["Messages"])

        # Логирование инициализации
        self._logger.info("MessageAPI initialized")
        self._register_endpoints()

    @property
    def message_router(self) -> APIRouter:
        return self._message_router

    def get_router(self) -> APIRouter:
        return self._message_router

    async def start_redis_listener(self):
        self._logger.info("Starting Redis listener for message delivery")
        self._redis_listener_task = asyncio.create_task(
            self.ws_manager.start_redis_listener()
        )
        self._logger.debug("Redis listener task created")

    async def stop_redis_listener(self):
        self._logger.info("Stopping Redis listener")
        if self._redis_listener_task:
            await self.ws_manager.stop_redis_listener()
            self._redis_listener_task.cancel()
            self._logger.debug("Redis listener task cancelled")

    async def _send_via_websocket(self, message: MessageResponse) -> bool:
        try:
            message_dict = message.dict()
            message_dict["type"] = "message"

            if message.recipient_id in self.ws_manager.active_connections:
                success = await self.ws_manager.send_personal_message(
                    message_dict,
                    message.recipient_id
                )
                if success:
                    self._logger.info(
                        "Message %s delivered instantly via WebSocket to user %s",
                        message.id, message.recipient_id
                    )
                    return True
                else:
                    self._logger.warning(
                        "Failed to deliver message %s via WebSocket to user %s",
                        message.id, message.recipient_id
                    )
            else:
                self._logger.debug(
                    "User %s is not connected via WebSocket, message %s will be delivered via Redis",
                    message.recipient_id, message.id
                )
            return False
        except Exception as e:
            self._logger.error(
                "WebSocket delivery failed for message %s: %s",
                message.id, str(e), exc_info=True
            )
            return False

    def _register_endpoints(self):
        @self.message_router.websocket("/ws")
        @inject
        async def websocket_endpoint(
                websocket: WebSocket,
                container: FromDishka[AsyncContainer]
        ):
            async with container() as request_container:
                user_service = await request_container.get(UserService)
                contact_service = await request_container.get(ContactService)

                token = websocket.query_params.get("token")
                if not token:
                    self._logger.warning("WebSocket connection attempted without token")
                    await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                    return

                user_id = None
                try:
                    user_id = await self._auth_api.get_current_user_ws(token)
                    if not user_id:
                        self._logger.warning("Invalid token for WebSocket connection")
                        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                        return

                    self._logger.info("WebSocket connection attempt from user %s", user_id)

                    contacts = await contact_service.get_contacts_by_user_id(user_id)
                    contact_ids = [
                        contact.sender_id if contact.sender_id != user_id else contact.receiver_id
                        for contact in contacts
                    ]

                    self._logger.debug("User %s has %s contacts", user_id, len(contact_ids))

                    await self.ws_manager.connect(user_id, websocket)
                    await self.ws_manager.broadcast_user_status(user_id=user_id, online=True, contact_ids=contact_ids)

                    await user_service.update_user(
                        user_id=user_id,
                        user=UserRequestDTO(
                            last_seen=datetime.utcnow(),
                            online=True
                        )
                    )

                    self._logger.info("WebSocket connected for user %s", user_id)
                    self._logger.debug("Broadcasted online status to %s contacts", len(contact_ids))

                    while True:
                        data = await websocket.receive_text()
                        if data == "ping":
                            self._logger.debug("Received ping from user %s", user_id)
                            await websocket.send_text("pong")
                        else:
                            self._logger.warning("Unexpected message from user %s: %s", user_id, data)

                except WebSocketDisconnect:
                    self._logger.info("WebSocket disconnected for user %s", user_id)
                    if user_id:
                        try:
                            contacts = await contact_service.get_contacts_by_user_id(user_id)
                            contact_ids = [
                                contact.sender_id if contact.sender_id != user_id else contact.receiver_id
                                for contact in contacts
                            ]
                            await self.ws_manager.disconnect(user_id)
                            await user_service.update_user(
                                user_id=user_id,
                                user=UserRequestDTO(
                                    last_seen=datetime.utcnow(),
                                    online=False
                                )
                            )
                            await self.ws_manager.broadcast_user_status(user_id, online=False, contact_ids=contact_ids)
                            self._logger.debug("Updated user %s status to offline and broadcasted to %s contacts",
                                               user_id, len(contact_ids))
                        except Exception as e:
                            self._logger.error("Error during WebSocket disconnect cleanup for user %s: %s",
                                               user_id, str(e), exc_info=True)

                except Exception as e:
                    self._logger.error("WebSocket error for user %s: %s", user_id, str(e), exc_info=True)
                    if user_id:
                        try:
                            contacts = await contact_service.get_contacts_by_user_id(user_id)
                            contact_ids = [
                                contact.sender_id if contact.sender_id != user_id else contact.receiver_id
                                for contact in contacts
                            ]
                            await self.ws_manager.disconnect(user_id)
                            await self.ws_manager.broadcast_user_status(user_id, online=False, contact_ids=contact_ids)
                            await user_service.update_user(
                                user_id=user_id,
                                user=UserRequestDTO(
                                    last_seen=datetime.utcnow(),
                                    online=False
                                )
                            )
                            self._logger.warning("Forcibly disconnected user %s due to error", user_id)
                        except Exception as cleanup_error:
                            self._logger.error("Error during error cleanup for user %s: %s",
                                               user_id, str(cleanup_error), exc_info=True)

        @self.message_router.post("/send", status_code=status.HTTP_201_CREATED)
        @inject
        async def send_message(
                message_data: MessageSendRequest,
                message_service: FromDishka[MessageService],
                token: str = Depends(self._auth_api.oauth2_scheme)
        ):
            sender_id = await self._auth_api.get_current_user(token)

            self._logger.info(
                "User %s sending message to user %s (content_type: %s)",
                sender_id, message_data.recipient_id, message_data.content_type
            )

            saved_message = await message_service.add_message(
                MessageRequestDTO(
                    sender_id=sender_id,
                    recipient_id=message_data.recipient_id,
                    message=message_data.message,
                    content_type=message_data.content_type,
                    timestamp=datetime.utcnow(),
                    is_delivered=False,
                    ephemeral_public_key=message_data.ephemeral_public_key,
                    ephemeral_signature=message_data.ephemeral_signature
                )
            )

            if not saved_message:
                self._logger.error("Failed to save message from user %s to user %s",
                                   sender_id, message_data.recipient_id)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to save message"
                )

            self._logger.debug("Message saved to database with ID: %s", saved_message.id)

            message_response = MessageResponse(
                id=saved_message.id,
                sender_id=saved_message.sender_id,
                recipient_id=saved_message.recipient_id,
                message=saved_message.message,
                content_type=saved_message.content_type,
                timestamp=datetime.utcnow().isoformat(),
                is_delivered=saved_message.is_delivered,
                ephemeral_public_key=saved_message.ephemeral_public_key,
                ephemeral_signature=saved_message.ephemeral_signature
            )

            delivered = await self._send_via_websocket(message_response)

            if not delivered:
                self._redis.publish(
                    "new_messages",
                    json.dumps(message_response.dict())
                )
                self._logger.info(
                    "Message %s published to Redis for background delivery (user %s offline)",
                    saved_message.id, message_data.recipient_id
                )
            else:
                self._logger.debug("Message %s delivered instantly via WebSocket", saved_message.id)

            return {
                "id": saved_message.id,
                "status": "sent",
                "delivered_instantly": delivered
            }

        @self.message_router.get("/undelivered", response_model=UndeliveredMessageResponse)
        @inject
        async def get_undelivered_messages(
                message_service: FromDishka[MessageService],
                token: str = Depends(self._auth_api.oauth2_scheme)
        ):
            user_id = await self._auth_api.get_current_user(token)
            self._logger.debug("User %s requesting undelivered messages", user_id)

            messages = await message_service.get_undelivered_messages(
                recipient_id=user_id
            )

            if messages:
                self._logger.info(
                    "User %s has %s undelivered messages",
                    user_id, len(messages)
                )
                message_responses = [
                    MessageResponse(
                        id=msg.id,
                        sender_id=msg.sender_id,
                        recipient_id=msg.recipient_id,
                        message=msg.message,
                        content_type=msg.content_type,
                        timestamp=msg.timestamp.isoformat(),
                        is_delivered=msg.is_delivered,
                        ephemeral_public_key=msg.ephemeral_public_key,
                        ephemeral_signature=msg.ephemeral_signature
                    ) for msg in messages
                ]
                return UndeliveredMessageResponse(
                    has_messages=True,
                    messages=message_responses,
                )

            self._logger.debug("User %s has no undelivered messages", user_id)
            return UndeliveredMessageResponse(has_messages=False)

        @self.message_router.post("/ack")
        @inject
        async def ack_messages(
                ack_data: AckRequest,
                message_service: FromDishka[MessageService],
                token: str = Depends(self._auth_api.oauth2_scheme)
        ):
            user_id = await self._auth_api.get_current_user(token)
            self._logger.info(
                "User %s acknowledging %s messages",
                user_id, len(ack_data.message_ids)
            )

            acked_messages = []
            failed_messages = []

            for msg_id in ack_data.message_ids:
                message = await message_service.get_message_by_id(msg_id)
                if message and message.recipient_id == user_id:
                    success = await message_service.mark_as_delivered(msg_id)
                    if success:
                        acked_messages.append(msg_id)
                        self._logger.debug("Message %s marked as delivered for user %s", msg_id, user_id)
                    else:
                        failed_messages.append(msg_id)
                        self._logger.warning("Failed to mark message %s as delivered for user %s", msg_id, user_id)
                else:
                    failed_messages.append(msg_id)
                    self._logger.warning(
                        "Message %s not found or user %s is not recipient",
                        msg_id, user_id
                    )

            self._logger.info(
                "User %s acknowledged %s/%s messages successfully",
                user_id, len(acked_messages), len(ack_data.message_ids)
            )

            if failed_messages:
                self._logger.warning("Failed to acknowledge messages: %s", failed_messages)

            return {
                "status": "acknowledged",
                "acked_messages": acked_messages,
                "failed_messages": failed_messages,
                "total_acked": len(acked_messages)
            }

        @self.message_router.get("/ws-status")
        async def get_websocket_status(
                token: str = Depends(self._auth_api.oauth2_scheme)
        ):
            user_id = await self._auth_api.get_current_user(token)
            is_connected = user_id in self.ws_manager.active_connections

            self._logger.debug(
                "WebSocket status check for user %s: connected=%s, total_connections=%s",
                user_id, is_connected, len(self.ws_manager.active_connections)
            )

            return {
                "user_id": user_id,
                "websocket_connected": is_connected,
                "active_connections": len(self.ws_manager.active_connections)
            }