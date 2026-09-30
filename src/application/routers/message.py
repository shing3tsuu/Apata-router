import logging
from typing import Annotated
from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Body, Depends, status
from fastapi.responses import JSONResponse

from src.adapters.database.dto import CreateMessageTextDTO
from src.adapters.database.service import MessageService
from src.adapters.encryption.service.jwt import JWTService
from src.adapters.realtime import RealtimePublisher
from src.application.models.message import (
    AcknowledgeMessagesRequest,
    AcknowledgeMessagesResponse,
    MessageTextResponse,
    SendTextMessageRequest,
    UndeliveredMessagesResponse,
)
from src.errors.error import ChatNotFoundError, ChatParticipantNotFoundError

from .user import AuthAPI


class MessageAPI:
    def __init__(self) -> None:
        self._message_router = APIRouter(tags=["Messages"])
        self._register_endpoints()

    def get_router(self) -> APIRouter:
        return self._message_router

    def _register_endpoints(self) -> None:
        @self._message_router.post(
            "/send",
            response_model=MessageTextResponse,
            status_code=status.HTTP_201_CREATED,
        )
        @inject
        async def send_text_message(
            request_data: SendTextMessageRequest,
            auth_api: FromDishka[AuthAPI],
            jwt_service: FromDishka[JWTService],
            message_service: FromDishka[MessageService],
            realtime_publisher: FromDishka[RealtimePublisher],
            logger: FromDishka[logging.Logger],
            token: str = Depends(AuthAPI.oauth2_scheme),
        ) -> MessageTextResponse | JSONResponse:
            current_user_id = await auth_api.get_current_user(
                token, jwt_service, logger
            )
            message = CreateMessageTextDTO(
                id=request_data.message_id,
                sender_id=current_user_id,
                recipient_id=request_data.recipient_id,
                chat_id=request_data.chat_id,
                reply_to_id=request_data.reply_to_id,
                content_type=request_data.content_type,
                content=request_data.message,
                ephemeral_public_key=request_data.ephemeral_public_key,
                ephemeral_signature=request_data.ephemeral_signature,
            )

            if request_data.chat_id is None:
                saved_message = await message_service.add_text_message(message)
            else:
                try:
                    saved_message = (
                        await message_service.add_chat_messages([message])
                    )[0]
                except ChatNotFoundError as error:
                    return JSONResponse(
                        status_code=status.HTTP_404_NOT_FOUND,
                        content={
                            "code": "chat_not_found",
                            "detail": error.message,
                            "status_code": status.HTTP_404_NOT_FOUND,
                        },
                    )
                except ChatParticipantNotFoundError:
                    return JSONResponse(
                        status_code=status.HTTP_403_FORBIDDEN,
                        content={
                            "code": "chat_participant_forbidden",
                            "detail": "Chat participant access is forbidden",
                            "status_code": status.HTTP_403_FORBIDDEN,
                        },
                    )

            logger.info(
                "Text message sent: message=%s sender=%s recipient=%s chat=%s",
                saved_message.id,
                current_user_id,
                saved_message.recipient_id,
                saved_message.chat_id,
            )
            await realtime_publisher.publish(
                "message_available",
                [saved_message.recipient_id],
                {
                    "message_id": str(saved_message.id),
                    "sender_id": str(saved_message.sender_id),
                    "chat_id": (
                        str(saved_message.chat_id)
                        if saved_message.chat_id is not None
                        else None
                    ),
                },
            )
            return MessageTextResponse.model_validate(saved_message)

        @self._message_router.post(
            "/chats/{chat_id}/messages",
            response_model=list[MessageTextResponse],
            status_code=status.HTTP_201_CREATED,
        )
        @inject
        async def send_chat_text_messages(
            chat_id: UUID,
            request_data: Annotated[
                list[SendTextMessageRequest], Body(min_length=1, max_length=100)
            ],
            auth_api: FromDishka[AuthAPI],
            jwt_service: FromDishka[JWTService],
            message_service: FromDishka[MessageService],
            realtime_publisher: FromDishka[RealtimePublisher],
            logger: FromDishka[logging.Logger],
            token: str = Depends(AuthAPI.oauth2_scheme),
        ) -> list[MessageTextResponse] | JSONResponse:
            current_user_id = await auth_api.get_current_user(
                token, jwt_service, logger
            )
            messages = [
                CreateMessageTextDTO(
                    id=message.message_id,
                    sender_id=current_user_id,
                    recipient_id=message.recipient_id,
                    chat_id=chat_id,
                    reply_to_id=message.reply_to_id,
                    content_type=message.content_type,
                    content=message.message,
                    ephemeral_public_key=message.ephemeral_public_key,
                    ephemeral_signature=message.ephemeral_signature,
                )
                for message in request_data
            ]

            try:
                saved_messages = await message_service.add_chat_messages(messages)
            except ChatNotFoundError as error:
                return JSONResponse(
                    status_code=status.HTTP_404_NOT_FOUND,
                    content={
                        "code": "chat_not_found",
                        "detail": error.message,
                        "status_code": status.HTTP_404_NOT_FOUND,
                    },
                )
            except ChatParticipantNotFoundError:
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={
                        "code": "chat_participant_forbidden",
                        "detail": "Chat participant access is forbidden",
                        "status_code": status.HTTP_403_FORBIDDEN,
                    },
                )

            logger.info(
                "Chat text message batch sent: chat=%s sender=%s messages=%s",
                chat_id,
                current_user_id,
                len(saved_messages),
            )
            await realtime_publisher.publish(
                "message_available",
                [message.recipient_id for message in saved_messages],
                {
                    "chat_id": str(chat_id),
                    "sender_id": str(current_user_id),
                },
            )
            return [
                MessageTextResponse.model_validate(message)
                for message in saved_messages
            ]

        @self._message_router.get(
            "/undelivered", response_model=UndeliveredMessagesResponse
        )
        @inject
        async def get_undelivered_messages(
            auth_api: FromDishka[AuthAPI],
            jwt_service: FromDishka[JWTService],
            message_service: FromDishka[MessageService],
            logger: FromDishka[logging.Logger],
            token: str = Depends(AuthAPI.oauth2_scheme),
        ) -> UndeliveredMessagesResponse:
            current_user_id = await auth_api.get_current_user(
                token, jwt_service, logger
            )
            messages = await message_service.get_undelivered_messages(current_user_id)
            text_messages = [
                MessageTextResponse.model_validate(message) for message in messages
            ]
            return UndeliveredMessagesResponse(
                has_messages=bool(text_messages), messages=text_messages
            )

        @self._message_router.post("/ack", response_model=AcknowledgeMessagesResponse)
        @inject
        async def acknowledge_messages(
            request_data: AcknowledgeMessagesRequest,
            auth_api: FromDishka[AuthAPI],
            jwt_service: FromDishka[JWTService],
            message_service: FromDishka[MessageService],
            logger: FromDishka[logging.Logger],
            token: str = Depends(AuthAPI.oauth2_scheme),
        ) -> AcknowledgeMessagesResponse:
            current_user_id = await auth_api.get_current_user(
                token, jwt_service, logger
            )
            acknowledged = await message_service.acknowledge_messages(
                current_user_id, request_data.message_ids
            )
            return AcknowledgeMessagesResponse(acknowledged=acknowledged)
