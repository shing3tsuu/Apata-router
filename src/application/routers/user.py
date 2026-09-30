import json
import logging
import os
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import redis.asyncio as redis
from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    status,
)
from fastapi.security import OAuth2PasswordBearer
from jose import ExpiredSignatureError, JWTError
from redis.exceptions import RedisError
from slowapi import Limiter
from slowapi.util import get_remote_address

from src.adapters.database.dto import CreateUserDTO, UpdateUserDTO
from src.adapters.database.service import UserService
from src.adapters.encryption.dto import SignatureAlgorithmEnum
from src.adapters.encryption.service.ed import EDService
from src.adapters.encryption.service.jwt import JWTService
from src.errors.error import InvalidAccessTokenTypeError, MissingAccessTokenSubjectError

from ..models.user import (
    ChallengeLoginRequest,
    ChallengeRequest,
    PublicKeyResponse,
    PublicKeyUpdateDTO,
    UserRegisterRequest,
    UserRegisterResponse,
    UserResponse,
)

CHALLENGE_EXPIRE_MINUTES = 5


class AuthAPI:
    oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

    def __init__(self) -> None:
        self._limiter = Limiter(key_func=get_remote_address)
        self._register_rate_limit = os.getenv("AUTH_REGISTER_RATE_LIMIT", "20/minute")
        self._auth_router = APIRouter(tags=["Authentication"])
        self._register_endpoints()

    def get_limiter(self) -> Limiter:
        return self._limiter

    @property
    def auth_router(self) -> APIRouter:
        return self._auth_router

    def get_router(self) -> APIRouter:
        return self._auth_router

    async def get_current_user(
        self,
        token: str,
        jwt_service: JWTService,
        logger: logging.Logger,
    ) -> UUID:
        try:
            user_id = await jwt_service.get_access_token_user_id(token)

            logger.debug("Token validated for user_id: %s", user_id)
            return user_id
        except InvalidAccessTokenTypeError:
            logger.warning("Invalid token type received")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
            ) from None
        except MissingAccessTokenSubjectError:
            logger.warning("Token with no subject received")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
            ) from None
        except ExpiredSignatureError:
            logger.warning("Expired token received")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token expired",
            ) from None
        except (JWTError, ValueError) as e:
            logger.warning("Invalid token received: %s", str(e))
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            ) from e
        except Exception as e:
            logger.critical("Error validating token: %s", str(e), exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Internal server error",
            )

    async def get_current_user_ws(
        self,
        token: str,
        jwt_service: JWTService,
        logger: logging.Logger,
    ) -> UUID | None:
        try:
            user_id = await jwt_service.get_access_token_user_id(token)
            logger.debug("WebSocket token validated for user_id: %s", user_id)
            return user_id
        except (ExpiredSignatureError, JWTError, ValueError) as e:
            logger.debug("WebSocket token validation failed: %s", str(e))
            return None
        except Exception:
            logger.exception("WebSocket token validation error")
            return None

    def _register_endpoints(self):
        async def issue_challenge(
            username: str,
            user_service: UserService,
            redis_client: redis.Redis,
            logger: logging.Logger,
        ) -> dict[str, str]:
            logger.info("Challenge request for username: %s", username)

            user = await user_service.get_users_by_name(username=username, limit=None)
            if not user:
                logger.warning("User not found for challenge: %s", username)
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
                )

            challenge = secrets.token_urlsafe(32)
            expires = datetime.now(UTC) + timedelta(minutes=CHALLENGE_EXPIRE_MINUTES)
            challenge_data = {
                "challenge": challenge,
                "expires": expires.isoformat(),
                "user_id": str(user.id),
            }

            await redis_client.setex(
                f"challenge:{username}",
                timedelta(minutes=CHALLENGE_EXPIRE_MINUTES),
                json.dumps(challenge_data),
            )

            logger.info("Challenge generated for user: %s (ID: %s)", username, user.id)
            return {"challenge": challenge, "expires": expires.isoformat()}

        @self.auth_router.post(
            "/register",
            status_code=status.HTTP_201_CREATED,
            response_model=UserRegisterResponse,
        )
        @self.auth_router.post(
            "/auth/register",
            status_code=status.HTTP_201_CREATED,
            response_model=UserRegisterResponse,
        )
        @self._limiter.limit(self._register_rate_limit)
        @inject
        async def register(
            request: Request,
            user_data: UserRegisterRequest,
            user_service: FromDishka[UserService],
            logger: FromDishka[logging.Logger],
        ):
            logger.info("Registration attempt for username: %s", user_data.username)

            existing_user = await user_service.get_users_by_name(
                username=user_data.username,
                limit=None,
            )
            if existing_user:
                logger.warning("Username already exists: %s", user_data.username)
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Username already exists",
                )

            user = await user_service.create_user(
                CreateUserDTO(
                    username=user_data.username,
                    ed_public_key=user_data.ed_public_key,
                    ecdh_public_key=user_data.ecdh_public_key,
                    ecdh_signature=user_data.ecdh_signature,
                    last_seen=datetime.now(UTC),
                    online=True,
                )
            )

            logger.info(
                "User registered successfully: %s (ID: %s)", user.username, user.id
            )
            return UserRegisterResponse(id=user.id, username=user.username)

        @self.auth_router.get("/challenge/{username}")
        @self._limiter.limit("30/minute")
        @inject
        async def get_challenge(
            request: Request,
            username: str,
            user_service: FromDishka[UserService],
            redis_client: FromDishka[redis.Redis],
            logger: FromDishka[logging.Logger],
        ):
            return await issue_challenge(username, user_service, redis_client, logger)

        @self.auth_router.post("/auth/challenges")
        @self._limiter.limit("30/minute")
        @inject
        async def get_challenge_from_body(
            request: Request,
            challenge_request: ChallengeRequest,
            user_service: FromDishka[UserService],
            redis_client: FromDishka[redis.Redis],
            logger: FromDishka[logging.Logger],
        ):
            return await issue_challenge(
                challenge_request.username,
                user_service,
                redis_client,
                logger,
            )

        @self.auth_router.post("/login", response_model=dict[str, Any])
        @self.auth_router.post("/auth/login", response_model=dict[str, Any])
        @self._limiter.limit("30/minute")
        @inject
        async def login(
            request: Request,
            login_data: ChallengeLoginRequest,
            user_service: FromDishka[UserService],
            jwt_service: FromDishka[JWTService],
            ed_service: FromDishka[EDService],
            redis_client: FromDishka[redis.Redis],
            logger: FromDishka[logging.Logger],
        ):
            logger.info("Login attempt for username: %s", login_data.username)

            # Check if challenge exists in Redis
            challenge_key = f"challenge:{login_data.username}"
            challenge_data_json = await redis_client.get(challenge_key)
            if not challenge_data_json:
                logger.warning(
                    "No challenge found for username: %s", login_data.username
                )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Challenge not found or expired",
                )

            challenge_data = json.loads(challenge_data_json)

            # Check challenge expiration
            expires = datetime.fromisoformat(challenge_data["expires"])
            if datetime.now(UTC) > expires:
                await redis_client.delete(challenge_key)
                logger.warning(
                    "Expired challenge for username: %s", login_data.username
                )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail="Challenge expired"
                )

            # Get user and public key
            user = await user_service.get_users_by_name(
                username=login_data.username, limit=None
            )
            if not user:
                logger.warning("User not found during login: %s", login_data.username)
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
                )

            if user.ed_public_key is None:
                logger.error("ED public key is missing for user: %s", user.id)
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="User has no ED public key",
                )

            # Verify signature
            is_valid = await ed_service.verify_signature(
                SignatureAlgorithmEnum.ED25519.value,
                user.ed_public_key,
                challenge_data["challenge"],
                login_data.signature,
            )

            if not is_valid:
                logger.warning(
                    "Invalid signature for username: %s", login_data.username
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature"
                )

            # Remove used challenge from Redis
            await redis_client.delete(challenge_key)

            # Create access token
            access_token = await jwt_service.create_access_token(user.id)

            logger.info(
                "Login successful for user: %s (ID: %s)", login_data.username, user.id
            )
            return {
                "access_token": access_token,
                "token_type": "bearer",
                "expires_in": jwt_service.access_token_expires_in_seconds,
            }

        @self.auth_router.post("/logout")
        @inject
        async def logout(
            jwt_service: FromDishka[JWTService],
            logger: FromDishka[logging.Logger],
            token: str = Depends(self.oauth2_scheme),
        ):
            user_id = await self.get_current_user(token, jwt_service, logger)
            # TODO maybe add some logic, and invalidation jwt token before expire time of course
            logger.info("User logout: ID %s", user_id)
            return {"status": "success", "message": "Logged out successfully"}

        @self.auth_router.delete("/auth/tokens/current")
        @inject
        async def logout_current_token(
            jwt_service: FromDishka[JWTService],
            logger: FromDishka[logging.Logger],
            token: str = Depends(self.oauth2_scheme),
        ) -> dict[str, str]:
            """Client-compatible logout endpoint for the current access token."""
            user_id = await self.get_current_user(token, jwt_service, logger)
            logger.info("User logout: ID %s", user_id)
            return {}

        @self.auth_router.get(
            "/public-keys/{user_id}", response_model=PublicKeyResponse
        )
        @inject
        async def get_public_keys(
            user_id: UUID,
            user_service: FromDishka[UserService],
            jwt_service: FromDishka[JWTService],
            logger: FromDishka[logging.Logger],
            token: str = Depends(self.oauth2_scheme),
        ):
            await self.get_current_user(token, jwt_service, logger)
            logger.debug("Public keys request for user_id: %s", user_id)

            user_data = await user_service.get_users_by_id(user_id)
            if user_data is None:
                logger.warning("User not found for public keys: %s", user_id)
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Public keys not found",
                )

            ecdh_public_key = user_data.ecdh_public_key
            ed_public_key = user_data.ed_public_key

            if not ed_public_key or not ecdh_public_key:
                logger.warning("Public keys not found for user_id: %s", user_id)
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Public keys not found",
                )

            logger.debug("Public keys retrieved for user_id: %s", user_id)
            return PublicKeyResponse(
                user_id=user_id,
                ed_public_key=ed_public_key,
                ecdh_public_key=ecdh_public_key,
                ecdh_signature=user_data.ecdh_signature,
            )

        @self.auth_router.put("/ecdsa-update-key", status_code=status.HTTP_200_OK)
        @inject
        async def update_ed_public_key(
            key_data: PublicKeyUpdateDTO,
            user_service: FromDishka[UserService],
            jwt_service: FromDishka[JWTService],
            logger: FromDishka[logging.Logger],
            token: str = Depends(self.oauth2_scheme),
        ):
            if key_data.ed_public_key is None:
                logger.warning("ECDSA public key is missing in update request")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="ECDSA public key is required",
                )

            user_id = await self.get_current_user(token, jwt_service, logger)
            logger.info("ECDSA key update request for user_id: %s", user_id)

            success = await user_service.update_user(
                user_id=user_id,
                user=UpdateUserDTO(ed_public_key=key_data.ed_public_key),
            )

            if not success:
                logger.error(
                    "Failed to update ECDSA public key for user_id: %s", user_id
                )
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to update public key",
                )

            logger.info(
                "ECDSA public key updated successfully for user_id: %s", user_id
            )
            return {"status": "ecdsa public key updated"}

        @self.auth_router.patch("/ecdh-update-key", status_code=status.HTTP_200_OK)
        @self.auth_router.put("/ecdh-update-key", status_code=status.HTTP_200_OK)
        @inject
        async def update_ecdh_public_key(
            key_data: PublicKeyUpdateDTO,
            user_service: FromDishka[UserService],
            jwt_service: FromDishka[JWTService],
            logger: FromDishka[logging.Logger],
            token: str = Depends(self.oauth2_scheme),
        ):
            if key_data.ecdh_public_key is None:
                logger.warning("ECDH public key is missing in update request")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="ECDH public key is required",
                )

            user_id = await self.get_current_user(token, jwt_service, logger)
            logger.info("ECDH key update request for user_id: %s", user_id)

            success = await user_service.update_user(
                user_id=user_id,
                user=UpdateUserDTO(
                    ecdh_public_key=key_data.ecdh_public_key,
                    ecdh_signature=key_data.ecdh_signature,
                ),
            )

            if not success:
                logger.error(
                    "Failed to update ECDH public key for user_id: %s", user_id
                )
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to update public key",
                )

            logger.info("ECDH public key updated successfully for user_id: %s", user_id)
            return {"status": "ecdh public key updated"}

        @self.auth_router.get("/me", response_model=UserResponse)
        @inject
        async def get_current_user_info(
            user_service: FromDishka[UserService],
            jwt_service: FromDishka[JWTService],
            logger: FromDishka[logging.Logger],
            token: str = Depends(self.oauth2_scheme),
        ):
            user_id = await self.get_current_user(token, jwt_service, logger)
            logger.debug("Current user info request for user_id: %s", user_id)

            user = await user_service.get_users_by_id(user_id)
            if not user:
                logger.error("User not found for ID: %s during /me request", user_id)
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
                )

            logger.debug("User info retrieved for user_id: %s", user_id)
            return UserResponse(
                id=user.id,
                username=user.username,
                ed_public_key=user.ed_public_key,
                ecdh_public_key=user.ecdh_public_key,
                ecdh_signature=user.ecdh_signature,
            )

        @self.auth_router.get("/health")
        @self._limiter.limit("10/minute")
        @inject
        async def health_check(
            request: Request,
            redis_client: FromDishka[redis.Redis],
            logger: FromDishka[logging.Logger],
        ):
            logger.debug("Health check request")
            try:
                # Check Redis connection
                await redis_client.ping()
                logger.debug("Health check passed")
                return {
                    "status": "healthy",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "service": "auth",
                    "redis": "connected",
                }
            except RedisError as e:
                logger.error("Health check failed: %s", str(e))
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Service unavailable",
                )
