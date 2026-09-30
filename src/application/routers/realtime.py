import logging

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from src.adapters.encryption.service.jwt import JWTService
from src.adapters.realtime import (
    RealtimeConnectionManager,
    RealtimePublisher,
)
from src.application.models.realtime import RealtimeEvent
from src.application.services import RealtimePresenceService

from .user import AuthAPI


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

            user_id = await auth_api.get_current_user_ws(
                token,
                jwt_service,
                logger,
            )
            if user_id is None:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return

            connected = False
            try:
                first_connection = await connection_manager.connect(
                    user_id,
                    websocket,
                )
                connected = True
                await websocket.send_json(
                    RealtimeEvent(
                        type="session_ready",
                        payload={"user_id": str(user_id)},
                    ).model_dump(mode="json")
                )

                if first_connection:
                    presence_time, contact_ids = await presence_service.set_presence(
                        user_id,
                        online=True,
                    )
                    await realtime_publisher.publish(
                        "presence_changed",
                        contact_ids,
                        {
                            "user_id": str(user_id),
                            "online": True,
                            "last_seen": presence_time.isoformat(),
                        },
                    )

                while True:
                    await websocket.receive_text()
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
                    if last_connection:
                        (
                            presence_time,
                            contact_ids,
                        ) = await presence_service.set_presence(
                            user_id,
                            online=False,
                        )
                        await realtime_publisher.publish(
                            "presence_changed",
                            contact_ids,
                            {
                                "user_id": str(user_id),
                                "online": False,
                                "last_seen": presence_time.isoformat(),
                            },
                        )
