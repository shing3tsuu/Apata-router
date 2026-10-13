import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from jose import ExpiredSignatureError
from pydantic import ValidationError

from src.adapters.encryption.service.jwt import JWTService
from src.adapters.realtime import (
    RealtimeConnectionManager,
    RealtimePublisher,
)
from src.application.models.realtime import RealtimeEvent, RealtimePresenceUpdate
from src.application.services import RealtimePresenceService

from .user import AuthAPI

ACCESS_TOKEN_EXPIRED_CLOSE_CODE = 4401
ACCESS_TOKEN_EXPIRED_CLOSE_REASON = "access_token_expired"


async def _receive_before_access_token_expiration(
    websocket: WebSocket,
    token_expires_at: datetime,
) -> str | None:
    seconds_until_expiration = (
        token_expires_at - datetime.now(UTC)
    ).total_seconds()
    if seconds_until_expiration <= 0:
        await websocket.close(
            code=ACCESS_TOKEN_EXPIRED_CLOSE_CODE,
            reason=ACCESS_TOKEN_EXPIRED_CLOSE_REASON,
        )
        return None
    try:
        return await asyncio.wait_for(
            websocket.receive_text(),
            timeout=seconds_until_expiration,
        )
    except TimeoutError:
        await websocket.close(
            code=ACCESS_TOKEN_EXPIRED_CLOSE_CODE,
            reason=ACCESS_TOKEN_EXPIRED_CLOSE_REASON,
        )
        return None


async def _publish_presence(
    user_id: UUID,
    *,
    online: bool,
    presence_service: RealtimePresenceService,
    realtime_publisher: RealtimePublisher,
) -> None:
    presence_time, contact_ids = await presence_service.set_presence(
        user_id,
        online=online,
    )
    await realtime_publisher.publish(
        "presence_changed",
        contact_ids,
        {
            "user_id": str(user_id),
            "online": online,
            "last_seen": presence_time.isoformat(),
        },
    )


class RealtimeAPI:
    def __init__(self) -> None:
        self._router = APIRouter(tags=["Realtime"])
        self._register_endpoints()

    def get_router(self) -> APIRouter:
        return self._router

    def _register_endpoints(self) -> None:
        @self._router.websocket("/ws")
        @inject
        async def websocket_endpoint(
            websocket: WebSocket,
            auth_api: FromDishka[AuthAPI],
            jwt_service: FromDishka[JWTService],
            connection_manager: FromDishka[RealtimeConnectionManager],
            presence_service: FromDishka[RealtimePresenceService],
            realtime_publisher: FromDishka[RealtimePublisher],
            logger: FromDishka[logging.Logger],
        ) -> None:
            authorization = websocket.headers.get("authorization", "")
            bearer_token = (
                authorization.removeprefix("Bearer ").strip()
                if authorization.startswith("Bearer ")
                else ""
            )
            token = bearer_token or websocket.query_params.get("token", "")
            if not token:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return

            try:
                user_id = await auth_api.get_current_user_ws(
                    token,
                    jwt_service,
                    logger,
                )
                token_expires_at = (
                    await jwt_service.get_access_token_expiration(token)
                    if user_id is not None
                    else None
                )
            except ExpiredSignatureError:
                await websocket.accept()
                await websocket.close(
                    code=ACCESS_TOKEN_EXPIRED_CLOSE_CODE,
                    reason=ACCESS_TOKEN_EXPIRED_CLOSE_REASON,
                )
                return
            if user_id is None:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return
            if token_expires_at is None:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return

            connected = False
            reported_online: bool | None = None
            try:
                await connection_manager.connect(
                    user_id,
                    websocket,
                )
                connected = True
                await websocket.send_json(
                    RealtimeEvent(
                        type="presence",
                        payload={"user_id": str(user_id)},
                    ).model_dump(mode="json")
                )

                while True:
                    raw_message = await _receive_before_access_token_expiration(
                        websocket,
                        token_expires_at,
                    )
                    if raw_message is None:
                        break
                    try:
                        presence_update = RealtimePresenceUpdate.model_validate_json(
                            raw_message
                        )
                    except ValidationError:
                        logger.warning(
                            "Ignoring invalid realtime command from user=%s",
                            user_id,
                        )
                        continue

                    if presence_update.online == reported_online:
                        continue

                    await _publish_presence(
                        user_id,
                        online=presence_update.online,
                        presence_service=presence_service,
                        realtime_publisher=realtime_publisher,
                    )
                    reported_online = presence_update.online
            except WebSocketDisconnect:
                pass
            except Exception:
                logger.exception("Realtime WebSocket failed for user=%s", user_id)
            finally:
                if connected:
                    last_connection = await connection_manager.disconnect(
                        user_id,
                        websocket,
                    )
                    if last_connection and reported_online is not False:
                        await _publish_presence(
                            user_id,
                            online=False,
                            presence_service=presence_service,
                            realtime_publisher=realtime_publisher,
                        )
