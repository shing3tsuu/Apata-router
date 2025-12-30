import logging
import base64
import asyncio
import secrets
import json
import redis

from slowapi import Limiter
from slowapi.util import get_remote_address

from fastapi import FastAPI, status, HTTPException, Depends, APIRouter, BackgroundTasks, Request
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional

from dishka import FromDishka
from dishka.integrations.fastapi import inject

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.backends import default_backend

from src.adapters.database.service import (
    UserService,
    ContactService,
    MessageService
)
from src.adapters.database.dto import UserRequestDTO, ContactRequestDTO, MessageRequestDTO
from ..models.auth_api_models import *


class AuthAPI:
    __slots__ = (
        "_redis",
        "_logger",
        "_limiter",
        "SECRET_KEY",
        "ALGORITHM",
        "ACCESS_TOKEN_EXPIRE_MINUTES",
        "CHALLENGE_EXPIRE_MINUTES",
        "oauth2_scheme",
        "_auth_router",
        "__weakref__"
    )

    def __init__(
            self,
            secret_key: str,
            redis_client: redis.Redis,
            logger: logging.Logger
    ):
        self._redis = redis_client
        self._logger = logger
        self._limiter = Limiter(key_func=get_remote_address)

        self.SECRET_KEY = secret_key
        self.ALGORITHM = "HS256"
        self.ACCESS_TOKEN_EXPIRE_MINUTES: int = 480  # 8 hours
        self.CHALLENGE_EXPIRE_MINUTES: int = 5
        self.oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")
        self._auth_router = APIRouter(tags=["Authentication"])
        self._register_endpoints()

    def get_limiter(self) -> Limiter:
        return self._limiter

    @property
    def auth_router(self) -> APIRouter:
        return self._auth_router

    def get_router(self) -> APIRouter:
        return self._auth_router

    def create_access_token(self, user_id: int) -> str:
        try:
            expires_delta = timedelta(minutes=self.ACCESS_TOKEN_EXPIRE_MINUTES)
            expire = datetime.now(timezone.utc) + expires_delta

            payload = {
                "sub": str(user_id),
                "exp": expire,
                "type": "access",
                "iat": datetime.now(timezone.utc)
            }
            token = jwt.encode(payload, self.SECRET_KEY, algorithm=self.ALGORITHM)
            self._logger.debug("Access token created for user_id: %s, expires: %s", user_id, expire)
            return token
        except Exception as e:
            self._logger.error("Error creating access token: %s", str(e), exc_info=True)
            raise

    async def get_current_user(self, token: str) -> int:
        try:
            payload = jwt.decode(token, self.SECRET_KEY, algorithms=[self.ALGORITHM])
            # Check token type
            if payload.get("type") != "access":
                self._logger.warning("Invalid token type received")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token type"
                )

            user_id = payload.get("sub")
            if user_id is None:
                self._logger.warning("Token with no subject received")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid authentication credentials",
                )

            self._logger.debug("Token validated for user_id: %s", user_id)
            return int(user_id)
        except jwt.ExpiredSignatureError:
            self._logger.warning("Expired token received")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token expired"
            )
        except (JWTError, ValueError) as e:
            self._logger.warning("Invalid token received: %s", str(e))
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            ) from e
        except Exception as e:
            self._logger.critical("Error validating token: %s", str(e), exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Internal server error"
            )

    async def get_current_user_ws(self, token: str) -> int | None:
        # WebSocket version without HTTPException
        try:
            payload = jwt.decode(token, self.SECRET_KEY, algorithms=[self.ALGORITHM])
            if payload.get("type") != "access":
                self._logger.debug("WebSocket: Invalid token type")
                return None
            user_id = payload.get("sub")
            if user_id is None:
                self._logger.debug("WebSocket: Token with no subject")
                return None

            self._logger.debug("WebSocket token validated for user_id: %s", user_id)
            return int(user_id)
        except (jwt.ExpiredSignatureError, JWTError, ValueError) as e:
            self._logger.debug("WebSocket token validation failed: %s", str(e))
            return None
        except Exception as e:
            self._logger.error("WebSocket token validation error: %s", str(e), exc_info=True)
            return None

    async def verify_signature(self, public_key_pem: str, challenge: str, signature: str) -> bool:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._verify_signature, public_key_pem, challenge, signature)

    def _verify_signature(self, public_key_pem: str, challenge: str, signature: str) -> bool:
        try:
            ecdsa_public_key = serialization.load_pem_public_key(
                public_key_pem.encode(),
                backend=default_backend()
            )
            # Decode signature from base64
            signature_bytes = base64.b64decode(signature)
            # Verify signature using ECDSA with SHA256
            ecdsa_public_key.verify(
                signature_bytes,
                challenge.encode(),
                ec.ECDSA(hashes.SHA256())
            )
            self._logger.debug("Signature verification successful")
            return True
        except (InvalidSignature, ValueError) as e:
            self._logger.warning("Signature verification failed: %s", str(e))
            return False
        except Exception as e:
            self._logger.error("Error verifying signature: %s", str(e), exc_info=True)
            return False

    @staticmethod
    def _validate_public_key_format(key: str) -> bool:
        if not key or not isinstance(key, str):
            return False
        return key.startswith('-----BEGIN') and 'KEY-----' in key

    def _register_endpoints(self):
        @self.auth_router.post("/register", status_code=status.HTTP_201_CREATED, response_model=UserRegisterResponse)
        @self._limiter.limit("20/minute")
        @inject
        async def register(
                request: Request,
                user_data: UserRegisterRequest,
                user_service: FromDishka[UserService],
        ):
            self._logger.info("Registration attempt for username: %s", user_data.username)

            # Validate public keys format
            if not self._validate_public_key_format(user_data.ecdsa_public_key):
                self._logger.warning("Invalid ECDSA public key format for username: %s", user_data.username)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid ECDSA public key format"
                )

            existing_user = await user_service.get_users_by_name(
                username=user_data.username,
                limit=None,
            )
            if existing_user:
                self._logger.warning("Username already exists: %s", user_data.username)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Username already exists"
                )

            user = await user_service.create_user(
                UserRequestDTO(
                    username=user_data.username,
                    ecdsa_public_key=user_data.ecdsa_public_key,
                    ecdh_public_key=user_data.ecdh_public_key,
                    ecdh_signature=user_data.ecdh_signature,
                    last_seen=datetime.utcnow(),
                    online=True
                )
            )

            self._logger.info("User registered successfully: %s (ID: %s)", user.username, user.id)
            return UserRegisterResponse(id=user.id, username=user.username)

        @self.auth_router.get("/challenge/{username}")
        @self._limiter.limit("30/minute")
        @inject
        async def get_challenge(
                request: Request,
                username: str,
                user_service: FromDishka[UserService],
        ):
            self._logger.info("Challenge request for username: %s", username)

            user = await user_service.get_users_by_name(
                username=username,
                limit=None,
            )
            if not user:
                self._logger.warning("User not found for challenge: %s", username)
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found"
                )

            # Generate random challenge
            challenge = secrets.token_urlsafe(32)
            expires = datetime.utcnow() + timedelta(minutes=self.CHALLENGE_EXPIRE_MINUTES)

            # Store challenge in Redis
            challenge_data = {
                "challenge": challenge,
                "expires": expires.isoformat(),
                "user_id": user.id
            }

            self._redis.setex(
                f"challenge:{username}",
                timedelta(minutes=self.CHALLENGE_EXPIRE_MINUTES),
                json.dumps(challenge_data)
            )

            self._logger.info("Challenge generated for user: %s (ID: %s)", username, user.id)
            return {"challenge": challenge, "expires": expires.isoformat()}

        @self.auth_router.post("/login", response_model=dict[str, Any])
        @self._limiter.limit("30/minute")
        @inject
        async def login(
                request: Request,
                login_data: ChallengeLoginRequest,
                user_service: FromDishka[UserService]
        ):
            self._logger.info("Login attempt for username: %s", login_data.username)

            # Check if challenge exists in Redis
            challenge_key = f"challenge:{login_data.username}"
            challenge_data_json = self._redis.get(challenge_key)
            if not challenge_data_json:
                self._logger.warning("No challenge found for username: %s", login_data.username)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Challenge not found or expired"
                )

            challenge_data = json.loads(challenge_data_json)

            # Check challenge expiration
            expires = datetime.fromisoformat(challenge_data["expires"].replace('Z', '+00:00'))
            if datetime.utcnow() > expires:
                self._redis.delete(challenge_key)
                self._logger.warning("Expired challenge for username: %s", login_data.username)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Challenge expired"
                )

            # Get user and public key
            user = await user_service.get_users_by_name(
                username=login_data.username,
                limit=None
            )
            if not user:
                self._logger.warning("User not found during login: %s", login_data.username)
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found"
                )

            # Verify signature
            is_valid = await self.verify_signature(
                user.ecdsa_public_key,
                challenge_data["challenge"],
                login_data.signature
            )

            if not is_valid:
                self._logger.warning("Invalid signature for username: %s", login_data.username)
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid signature"
                )

            # Remove used challenge from Redis
            self._redis.delete(challenge_key)

            # Create access token
            access_token = self.create_access_token(user.id)

            self._logger.info("Login successful for user: %s (ID: %s)", login_data.username, user.id)
            return {
                "access_token": access_token,
                "token_type": "bearer",
                "expires_in": self.ACCESS_TOKEN_EXPIRE_MINUTES * 60
            }

        @self.auth_router.post("/logout")
        @inject
        async def logout(
                user_service: FromDishka[UserService],
                token: str = Depends(self.oauth2_scheme),
        ):
            user_id = await self.get_current_user(token)
            # TODO maybe add some logic, and invalidation jwt token before expire time of course
            self._logger.info("User logout: ID %s", user_id)
            return {"status": "success", "message": "Logged out successfully"}

        @self.auth_router.get("/public-keys/{user_id}", response_model=PublicKeyResponse)
        @inject
        async def get_public_keys(
                user_id: int,
                user_service: FromDishka[UserService],
                token: str = Depends(self.oauth2_scheme)
        ):
            await self.get_current_user(token)
            self._logger.debug("Public keys request for user_id: %s", user_id)

            user_data = await user_service.get_users_by_id(int(user_id))
            ecdh_public_key = user_data.ecdh_public_key
            ecdsa_public_key = user_data.ecdsa_public_key

            if not ecdsa_public_key or not ecdh_public_key:
                self._logger.warning("Public keys not found for user_id: %s", user_id)
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Public keys not found"
                )

            self._logger.debug("Public keys retrieved for user_id: %s", user_id)
            return PublicKeyResponse(
                user_id=user_id,
                ecdsa_public_key=ecdsa_public_key,
                ecdh_public_key=ecdh_public_key,
                ecdh_signature=user_data.ecdh_signature
            )

        @self.auth_router.put("/ecdsa-update-key", status_code=status.HTTP_200_OK)
        @inject
        async def update_ecdsa_public_key(
                key_data: PublicKeyUpdateDTO,
                user_service: FromDishka[UserService],
                token: str = Depends(self.oauth2_scheme)
        ):
            if not key_data.ecdsa_public_key or not self._validate_public_key_format(key_data.ecdsa_public_key):
                self._logger.warning("Invalid ECDSA public key format in update request")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid ECDSA public key format"
                )

            user_id = await self.get_current_user(token)
            self._logger.info("ECDSA key update request for user_id: %s", user_id)

            success = await user_service.update_user(
                user_id=user_id,
                user=UserRequestDTO(ecdsa_public_key=key_data.ecdsa_public_key)
            )

            if not success:
                self._logger.error("Failed to update ECDSA public key for user_id: %s", user_id)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to update public key"
                )

            self._logger.info("ECDSA public key updated successfully for user_id: %s", user_id)
            return {"status": "ecdsa public key updated"}

        @self.auth_router.put("/ecdh-update-key", status_code=status.HTTP_200_OK)
        @inject
        async def update_ecdh_public_key(
                key_data: PublicKeyUpdateDTO,
                user_service: FromDishka[UserService],
                token: str = Depends(self.oauth2_scheme)
        ):
            if not key_data.ecdh_public_key or not self._validate_public_key_format(key_data.ecdh_public_key):
                self._logger.warning("Invalid ECDH public key format in update request")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid ECDH public key format"
                )

            user_id = await self.get_current_user(token)
            self._logger.info("ECDH key update request for user_id: %s", user_id)

            success = await user_service.update_user(
                user_id=user_id,
                user=UserRequestDTO(
                    ecdh_public_key=key_data.ecdh_public_key,
                    ecdh_signature=key_data.ecdh_signature
                )
            )

            if not success:
                self._logger.error("Failed to update ECDH public key for user_id: %s", user_id)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to update public key"
                )

            self._logger.info("ECDH public key updated successfully for user_id: %s", user_id)
            return {"status": "ecdh public key updated"}

        @self.auth_router.get("/me", response_model=UserResponse)
        @inject
        async def get_current_user_info(
                user_service: FromDishka[UserService],
                token: str = Depends(self.oauth2_scheme)
        ):
            user_id = await self.get_current_user(token)
            self._logger.debug("Current user info request for user_id: %s", user_id)

            user = await user_service.get_users_by_id(int(user_id))
            if not user:
                self._logger.error("User not found for ID: %s during /me request", user_id)
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found"
                )

            self._logger.debug("User info retrieved for user_id: %s", user_id)
            return UserResponse(
                id=user.id,
                username=user.username,
                ecdsa_public_key=user.ecdsa_public_key,
                ecdh_public_key=user.ecdh_public_key,
                ecdh_signature=user.ecdh_signature
            )

        @self.auth_router.get("/health")
        @self._limiter.limit("10/minute")
        async def health_check(
                request: Request
        ):
            self._logger.debug("Health check request")
            try:
                # Check Redis connection
                self._redis.ping()
                self._logger.debug("Health check passed")
                return {
                    "status": "healthy",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "service": "auth",
                    "redis": "connected"
                }
            except Exception as e:
                self._logger.error("Health check failed: %s", str(e))
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Service unavailable"
                )