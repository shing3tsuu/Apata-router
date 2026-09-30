import logging
from datetime import datetime
from typing import NoReturn
from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Depends, HTTPException, status

from src.adapters.database.dto import (
    ChatDTO,
    ChatEventDTO,
    ChatParticipantChangeDTO,
    ChatParticipantDTO,
    CreateChatDTO,
    UpdateChatDTO,
)
from src.adapters.database.service import ChatService
from src.adapters.encryption.service.jwt import JWTService
from src.adapters.realtime import RealtimePublisher
from src.application.models.chat import (
    AddChatParticipantRequest,
    ChatEventResponse,
    ChatParticipantChangeResponse,
    ChatParticipantResponse,
    ChatResponse,
    CreateChatRequest,
    UpdateChatRequest,
)
from src.errors.error import (
    BaseAppError,
    ChatNotFoundError,
    ChatParticipantAlreadyExistsError,
    ChatParticipantNotFoundError,
    ChatPermissionDeniedError,
    UserNotFoundError,
)

from .user import AuthAPI


def _chat_response(chat: ChatDTO) -> ChatResponse:
    return ChatResponse.model_validate(chat, from_attributes=True)


def _participant_response(
    participant: ChatParticipantDTO,
    *,
    left_at: datetime | None = None,
) -> ChatParticipantResponse:
    return ChatParticipantResponse(
        chat_id=participant.chat_id,
        user_id=participant.user_id,
        invited_by_user_id=participant.invited_by_user_id,
        joined_at=participant.joined_at,
        left_at=left_at,
    )


def _event_response(event: ChatEventDTO) -> ChatEventResponse:
    return ChatEventResponse(
        id=event.id,
        chat_id=event.chat_id,
        user_id=event.actor_id,
        event_type=event.event_type.value,
        timestamp=event.timestamp,
        target_user_id=event.target_user_id,
    )


def _participant_change_response(
    change: ChatParticipantChangeDTO,
    *,
    left_at: bool = False,
) -> ChatParticipantChangeResponse:
    return ChatParticipantChangeResponse(
        participant=_participant_response(
            change.participant,
            left_at=change.event.timestamp if left_at else None,
        ),
        event=_event_response(change.event),
    )


def _raise_chat_http_error(error: BaseAppError) -> NoReturn:
    if isinstance(error, (ChatNotFoundError, UserNotFoundError)):
        status_code = status.HTTP_404_NOT_FOUND
    elif isinstance(error, ChatParticipantAlreadyExistsError):
        status_code = status.HTTP_409_CONFLICT
    elif isinstance(error, (ChatParticipantNotFoundError, ChatPermissionDeniedError)):
        status_code = status.HTTP_403_FORBIDDEN
    else:
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

    raise HTTPException(status_code=status_code, detail=error.message) from error


class ChatAPI:
    def __init__(self) -> None:
        self._chat_router = APIRouter(prefix="/chats", tags=["Chats"])
        self._register_endpoints()

    def get_router(self) -> APIRouter:
        return self._chat_router

    @staticmethod
    async def _get_current_user_id(
        token: str,
        auth_api: AuthAPI,
        jwt_service: JWTService,
        logger: logging.Logger,
    ) -> UUID:
        return await auth_api.get_current_user(token, jwt_service, logger)

    def _register_endpoints(self) -> None:
        @self._chat_router.get("", response_model=list[ChatResponse])
        @inject
        async def list_chats(
            auth_api: FromDishka[AuthAPI],
            jwt_service: FromDishka[JWTService],
            chat_service: FromDishka[ChatService],
            logger: FromDishka[logging.Logger],
            token: str = Depends(AuthAPI.oauth2_scheme),
        ) -> list[ChatResponse]:
            current_user_id = await self._get_current_user_id(
                token, auth_api, jwt_service, logger
            )
            chats = await chat_service.get_chats_by_user_id(current_user_id)
            return [_chat_response(chat) for chat in chats]

        @self._chat_router.post(
            "",
            response_model=ChatResponse,
            status_code=status.HTTP_201_CREATED,
        )
        @inject
        async def create_chat(
            request_data: CreateChatRequest,
            auth_api: FromDishka[AuthAPI],
            jwt_service: FromDishka[JWTService],
            chat_service: FromDishka[ChatService],
            realtime_publisher: FromDishka[RealtimePublisher],
            logger: FromDishka[logging.Logger],
            token: str = Depends(AuthAPI.oauth2_scheme),
        ) -> ChatResponse:
            current_user_id = await self._get_current_user_id(
                token, auth_api, jwt_service, logger
            )
            try:
                chat = await chat_service.create_chat(
                    CreateChatDTO(owner_id=current_user_id, name=request_data.name)
                )
            except BaseAppError as error:
                _raise_chat_http_error(error)

            logger.info("Chat created: chat=%s owner=%s", chat.id, current_user_id)
            await realtime_publisher.publish(
                "chat_changed",
                [current_user_id],
                {
                    "chat_id": str(chat.id),
                    "actor_id": str(current_user_id),
                    "action": "created",
                },
            )
            return _chat_response(chat)

        @self._chat_router.get("/{chat_id}", response_model=ChatResponse)
        @inject
        async def get_chat(
            chat_id: UUID,
            auth_api: FromDishka[AuthAPI],
            jwt_service: FromDishka[JWTService],
            chat_service: FromDishka[ChatService],
            logger: FromDishka[logging.Logger],
            token: str = Depends(AuthAPI.oauth2_scheme),
        ) -> ChatResponse:
            current_user_id = await self._get_current_user_id(
                token, auth_api, jwt_service, logger
            )
            try:
                chat = await chat_service.get_chat(chat_id, current_user_id)
            except BaseAppError as error:
                _raise_chat_http_error(error)
            return _chat_response(chat)

        @self._chat_router.patch("/{chat_id}", response_model=ChatResponse)
        @inject
        async def update_chat(
            chat_id: UUID,
            request_data: UpdateChatRequest,
            auth_api: FromDishka[AuthAPI],
            jwt_service: FromDishka[JWTService],
            chat_service: FromDishka[ChatService],
            realtime_publisher: FromDishka[RealtimePublisher],
            logger: FromDishka[logging.Logger],
            token: str = Depends(AuthAPI.oauth2_scheme),
        ) -> ChatResponse:
            current_user_id = await self._get_current_user_id(
                token, auth_api, jwt_service, logger
            )
            try:
                chat = await chat_service.update_chat(
                    chat_id,
                    current_user_id,
                    UpdateChatDTO(name=request_data.name),
                )
            except BaseAppError as error:
                _raise_chat_http_error(error)
            participants = await chat_service.get_participants(
                chat_id,
                current_user_id,
            )
            await realtime_publisher.publish(
                "chat_changed",
                [participant.user_id for participant in participants],
                {
                    "chat_id": str(chat_id),
                    "actor_id": str(current_user_id),
                    "action": "updated",
                },
            )
            return _chat_response(chat)

        @self._chat_router.delete("/{chat_id}", status_code=status.HTTP_200_OK)
        @inject
        async def delete_chat(
            chat_id: UUID,
            auth_api: FromDishka[AuthAPI],
            jwt_service: FromDishka[JWTService],
            chat_service: FromDishka[ChatService],
            realtime_publisher: FromDishka[RealtimePublisher],
            logger: FromDishka[logging.Logger],
            token: str = Depends(AuthAPI.oauth2_scheme),
        ) -> dict[str, bool]:
            current_user_id = await self._get_current_user_id(
                token, auth_api, jwt_service, logger
            )
            try:
                participants = await chat_service.get_participants(
                    chat_id,
                    current_user_id,
                )
                deleted = await chat_service.delete_chat(chat_id, current_user_id)
            except BaseAppError as error:
                _raise_chat_http_error(error)
            logger.info("Chat deleted: chat=%s owner=%s", chat_id, current_user_id)
            await realtime_publisher.publish(
                "chat_changed",
                [participant.user_id for participant in participants],
                {
                    "chat_id": str(chat_id),
                    "actor_id": str(current_user_id),
                    "action": "deleted",
                },
            )
            return {"deleted": deleted}

        @self._chat_router.get(
            "/{chat_id}/participants",
            response_model=list[ChatParticipantResponse],
        )
        @inject
        async def get_participants(
            chat_id: UUID,
            auth_api: FromDishka[AuthAPI],
            jwt_service: FromDishka[JWTService],
            chat_service: FromDishka[ChatService],
            logger: FromDishka[logging.Logger],
            token: str = Depends(AuthAPI.oauth2_scheme),
        ) -> list[ChatParticipantResponse]:
            current_user_id = await self._get_current_user_id(
                token, auth_api, jwt_service, logger
            )
            try:
                participants = await chat_service.get_participants(
                    chat_id, current_user_id
                )
            except BaseAppError as error:
                _raise_chat_http_error(error)
            return [_participant_response(participant) for participant in participants]

        @self._chat_router.post(
            "/{chat_id}/participants",
            response_model=ChatParticipantChangeResponse,
            status_code=status.HTTP_201_CREATED,
        )
        @inject
        async def add_participant(
            chat_id: UUID,
            request_data: AddChatParticipantRequest,
            auth_api: FromDishka[AuthAPI],
            jwt_service: FromDishka[JWTService],
            chat_service: FromDishka[ChatService],
            realtime_publisher: FromDishka[RealtimePublisher],
            logger: FromDishka[logging.Logger],
            token: str = Depends(AuthAPI.oauth2_scheme),
        ) -> ChatParticipantChangeResponse:
            current_user_id = await self._get_current_user_id(
                token, auth_api, jwt_service, logger
            )
            try:
                change = await chat_service.add_participant(
                    chat_id, current_user_id, request_data.user_id
                )
            except BaseAppError as error:
                _raise_chat_http_error(error)
            logger.info(
                "Chat participant added: chat=%s actor=%s participant=%s",
                chat_id,
                current_user_id,
                request_data.user_id,
            )
            participants = await chat_service.get_participants(
                chat_id,
                current_user_id,
            )
            await realtime_publisher.publish(
                "chat_changed",
                [participant.user_id for participant in participants],
                {
                    "chat_id": str(chat_id),
                    "event_id": str(change.event.id),
                    "actor_id": str(current_user_id),
                    "action": change.event.event_type.value,
                },
            )
            return _participant_change_response(change)

        @self._chat_router.delete(
            "/{chat_id}/participants/{user_id}",
            response_model=ChatParticipantChangeResponse,
        )
        @inject
        async def remove_participant(
            chat_id: UUID,
            user_id: UUID,
            auth_api: FromDishka[AuthAPI],
            jwt_service: FromDishka[JWTService],
            chat_service: FromDishka[ChatService],
            realtime_publisher: FromDishka[RealtimePublisher],
            logger: FromDishka[logging.Logger],
            token: str = Depends(AuthAPI.oauth2_scheme),
        ) -> ChatParticipantChangeResponse:
            current_user_id = await self._get_current_user_id(
                token, auth_api, jwt_service, logger
            )
            try:
                change = await chat_service.remove_participant(
                    chat_id, current_user_id, user_id
                )
            except BaseAppError as error:
                _raise_chat_http_error(error)
            logger.info(
                "Chat participant removed: chat=%s actor=%s participant=%s",
                chat_id,
                current_user_id,
                user_id,
            )
            participants = await chat_service.get_participants(
                chat_id,
                current_user_id,
            )
            await realtime_publisher.publish(
                "chat_changed",
                [
                    *(participant.user_id for participant in participants),
                    user_id,
                ],
                {
                    "chat_id": str(chat_id),
                    "event_id": str(change.event.id),
                    "actor_id": str(current_user_id),
                    "action": change.event.event_type.value,
                },
            )
            return _participant_change_response(change, left_at=True)

        @self._chat_router.post(
            "/{chat_id}/leave",
            response_model=ChatParticipantChangeResponse,
        )
        @inject
        async def leave_chat(
            chat_id: UUID,
            auth_api: FromDishka[AuthAPI],
            jwt_service: FromDishka[JWTService],
            chat_service: FromDishka[ChatService],
            realtime_publisher: FromDishka[RealtimePublisher],
            logger: FromDishka[logging.Logger],
            token: str = Depends(AuthAPI.oauth2_scheme),
        ) -> ChatParticipantChangeResponse:
            current_user_id = await self._get_current_user_id(
                token, auth_api, jwt_service, logger
            )
            try:
                participants = await chat_service.get_participants(
                    chat_id,
                    current_user_id,
                )
                change = await chat_service.leave_chat(chat_id, current_user_id)
            except BaseAppError as error:
                _raise_chat_http_error(error)
            await realtime_publisher.publish(
                "chat_changed",
                [
                    *(participant.user_id for participant in participants),
                    current_user_id,
                ],
                {
                    "chat_id": str(chat_id),
                    "event_id": str(change.event.id),
                    "actor_id": str(current_user_id),
                    "action": change.event.event_type.value,
                },
            )
            return _participant_change_response(change, left_at=True)

        @self._chat_router.get(
            "/{chat_id}/events", response_model=list[ChatEventResponse]
        )
        @inject
        async def get_events(
            chat_id: UUID,
            auth_api: FromDishka[AuthAPI],
            jwt_service: FromDishka[JWTService],
            chat_service: FromDishka[ChatService],
            logger: FromDishka[logging.Logger],
            after: datetime | None = None,
            token: str = Depends(AuthAPI.oauth2_scheme),
        ) -> list[ChatEventResponse]:
            current_user_id = await self._get_current_user_id(
                token, auth_api, jwt_service, logger
            )
            try:
                events = await chat_service.get_events(
                    chat_id,
                    current_user_id,
                    after=after,
                )
            except BaseAppError as error:
                _raise_chat_http_error(error)
            return [_event_response(event) for event in events]
