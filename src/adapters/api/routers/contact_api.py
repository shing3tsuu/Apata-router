import logging
import redis
from typing import List
from datetime import datetime

from fastapi import FastAPI, status, HTTPException, Depends, APIRouter
from dishka import FromDishka
from dishka.integrations.fastapi import inject

from src.adapters.database.service import (
    UserService,
    ContactService,
    MessageService
)
from src.adapters.database.dto import UserRequestDTO, ContactRequestDTO, MessageRequestDTO
from ..models.contact_api_models import *
from .auth_api import AuthAPI


class ContactAPI:
    def __init__(
            self,
            auth_api: AuthAPI,
            redis_client: redis.Redis,
            logger: logging.Logger
    ):
        self._redis = redis_client
        self._logger = logger
        self._auth_api = auth_api
        self._contact_router = APIRouter(tags=["Contacts"])

        self._register_endpoints()

    @property
    def contact_router(self) -> APIRouter:
        return self._contact_router

    def get_router(self) -> APIRouter:
        return self._contact_router

    def _register_endpoints(self):
        @self.contact_router.get("/search-users", response_model=list[UserContactResponse])
        @inject
        async def search_users(
                username: str,
                user_service: FromDishka[UserService],
                token: str = Depends(self._auth_api.oauth2_scheme)
        ):
            self._logger.info("Search users request for username pattern: %s", username)

            user_id = await self._auth_api.get_current_user(token)
            self._logger.debug("User %s searching for users with pattern: %s", user_id, username)

            users = await user_service.get_users_by_name(
                username=username,
                limit=10
            )

            if not users:
                self._logger.debug("No users found for pattern: %s", username)
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Users not found"
                )

            self._logger.info("Found %s users for pattern: %s", len(users), username)
            return [
                UserContactResponse(
                    id=user.id,
                    username=user.username,
                    ecdh_public_key=user.ecdh_public_key,
                    last_seen=user.last_seen,
                    online=user.online
                ) for user in users
            ]

        @self.contact_router.get("/users-by-ids", response_model=list[UserContactResponse])
        @inject
        async def get_users_by_ids(
                users_ids: str,
                user_service: FromDishka[UserService],
                token: str = Depends(self._auth_api.oauth2_scheme)
        ):
            current_user_id = await self._auth_api.get_current_user(token)
            self._logger.debug("User %s requesting users by IDs: %s", current_user_id, users_ids)

            # Convert comma-separated string to list of integers
            try:
                user_id_list = [int(user_id.strip()) for user_id in users_ids.split(',') if user_id.strip()]
                self._logger.debug("Parsed user IDs: %s", user_id_list)
            except ValueError as e:
                self._logger.warning("Invalid user IDs format: %s, error: %s", users_ids, str(e))
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid user IDs format"
                )

            if not user_id_list:
                self._logger.warning("Empty user IDs list provided")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No user IDs provided"
                )

            users = await user_service.get_users_with_contact_status_by_ids(
                current_user_id=current_user_id,
                user_ids=user_id_list
            )

            if not users:
                self._logger.debug("No users found for IDs: %s", user_id_list)
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Users not found"
                )

            self._logger.debug("Found %s users for IDs", len(users))
            return [
                UserContactResponse(
                    id=user.id,
                    username=user.username,
                    status=user.status,
                    ecdh_public_key=user.ecdh_public_key,
                    last_seen=user.last_seen,
                    online=user.online
                ) for user in users
            ]

        @self.contact_router.get("/get-contacts", response_model=list[ContactRequestResponse])
        @inject
        async def get_contacts(
                contact_service: FromDishka[ContactService],
                token: str = Depends(self._auth_api.oauth2_scheme)
        ):
            user_id = await self._auth_api.get_current_user(token)
            self._logger.debug("User %s requesting contacts list", user_id)

            contacts = await contact_service.get_contacts_by_user_id(
                user_id=user_id
            )

            if not contacts:
                self._logger.debug("User %s has no contacts", user_id)
                return []

            self._logger.debug("User %s has %s contacts", user_id, len(contacts))
            return [
                ContactRequestResponse(
                    sender_id=contact.sender_id,
                    receiver_id=contact.receiver_id,
                    status=contact.status,
                    created_at=contact.created_at
                ) for contact in contacts
            ]

        @self.contact_router.post("/send-contact-request", status_code=status.HTTP_201_CREATED)
        @inject
        async def send_contact_request(
                request_data: SentContactRequest,
                user_service: FromDishka[UserService],
                contact_service: FromDishka[ContactService],
                token: str = Depends(self._auth_api.oauth2_scheme)
        ):
            user_id = await self._auth_api.get_current_user(token)
            self._logger.info("User %s sending contact request to user %s", user_id, request_data.receiver_id)

            receiver = await user_service.get_users_by_id(
                user_ids=int(request_data.receiver_id),
            )

            if not receiver:
                self._logger.warning("Receiver user %s not found", request_data.receiver_id)
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Receiver user not found"
                )

            if user_id == receiver.id:
                self._logger.warning("User %s attempted to send contact request to themselves", user_id)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot send contact request to yourself"
                )

            check_contact = await contact_service.get_contact_requests(
                contact=ContactRequestDTO(
                    sender_id=user_id,
                    receiver_id=request_data.receiver_id
                ),
                is_all=False
            )

            if check_contact is not None:
                if check_contact.status in ['pending', 'accepted']:
                    self._logger.info("Contact request already exists between user %s and %s with status: %s",
                                      user_id, request_data.receiver_id, check_contact.status)
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="This contact request already exists"
                    )
                else:
                    self._logger.debug("Updating existing contact request (previous status: %s)", check_contact.status)
                    success = await contact_service.update_contact_request(
                        contact=ContactRequestDTO(
                            sender_id=user_id,
                            receiver_id=request_data.receiver_id,
                            status="pending"
                        )
                    )
                    if not success:
                        self._logger.error("Failed to update contact request from user %s to %s",
                                           user_id, request_data.receiver_id)
                        raise HTTPException(
                            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Failed to update contact request"
                        )

                    self._logger.info("Contact request updated successfully from user %s to %s",
                                      user_id, request_data.receiver_id)
                    return UserContactResponse(
                        id=receiver.id,
                        username=receiver.username,
                        status="pending",
                        ecdh_public_key=receiver.ecdh_public_key,
                        last_seen=receiver.last_seen
                    )

            self._logger.debug("Creating new contact request from user %s to %s", user_id, request_data.receiver_id)
            contact = await contact_service.add_contact_request(
                contact=ContactRequestDTO(
                    sender_id=user_id,
                    receiver_id=request_data.receiver_id,
                    status="pending",
                    created_at=datetime.utcnow()
                )
            )

            if not contact:
                self._logger.error("Failed to add contact request from user %s to %s",
                                   user_id, request_data.receiver_id)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to add contact request"
                )

            self._logger.info("Contact request created successfully from user %s to %s",
                              user_id, request_data.receiver_id)
            return UserContactResponse(
                id=receiver.id,
                username=receiver.username,
                status="pending",
                ecdh_public_key=receiver.ecdh_public_key,
                last_seen=receiver.last_seen,
                online=receiver.online
            )

        @self.contact_router.get("/get-contact-requests", response_model=list[ContactRequestResponse])
        @inject
        async def get_contact_requests(
                contact_service: FromDishka[ContactService],
                token: str = Depends(self._auth_api.oauth2_scheme)
        ):
            user_id = await self._auth_api.get_current_user(token)
            self._logger.debug("User %s requesting pending contact requests", user_id)

            contacts = await contact_service.get_contact_requests(
                ContactRequestDTO(
                    receiver_id=user_id,
                    status="pending"
                ),
                is_all=True
            )

            if not contacts:
                self._logger.debug("No pending contact requests for user %s", user_id)
                return []

            self._logger.debug("User %s has %s pending contact requests", user_id, len(contacts))
            return [
                ContactRequestResponse(
                    sender_id=contact.sender_id,
                    receiver_id=contact.receiver_id,
                    status=contact.status,
                    created_at=contact.created_at
                ) for contact in contacts
            ]

        @self.contact_router.put("/accept-contact-request", status_code=status.HTTP_200_OK)
        @inject
        async def accept_contact_request(
                request_data: SentContactRequest,
                contact_service: FromDishka[ContactService],
                token: str = Depends(self._auth_api.oauth2_scheme)
        ):
            user_id = await self._auth_api.get_current_user(token)
            self._logger.info("User %s accepting contact request from user %s",
                              user_id, request_data.receiver_id)

            check_contact = await contact_service.get_contact_requests(
                contact=ContactRequestDTO(
                    sender_id=request_data.receiver_id,
                    receiver_id=user_id,
                ),
                is_all=False
            )

            if check_contact is None:
                self._logger.warning("Contact request not found from user %s to %s",
                                     request_data.receiver_id, user_id)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Contact request not found"
                )

            if check_contact.status == "accepted":
                self._logger.info("Contact request already accepted from user %s to %s",
                                  request_data.receiver_id, user_id)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Contact request is already {check_contact.status}"
                )

            self._logger.debug("Accepting contact request (previous status: %s)", check_contact.status)
            contact = await contact_service.update_contact_request(
                contact=ContactRequestDTO(
                    sender_id=request_data.receiver_id,
                    receiver_id=user_id,
                    status="accepted"
                )
            )

            if not contact:
                self._logger.error("Failed to accept contact request from user %s to %s",
                                   request_data.receiver_id, user_id)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to accept contact request"
                )

            self._logger.info("Contact request accepted successfully from user %s to %s",
                              request_data.receiver_id, user_id)
            return {"status": "success accept contact request"}

        @self.contact_router.put("/reject-contact-request", status_code=status.HTTP_200_OK)
        @inject
        async def reject_contact_request(
                request_data: SentContactRequest,
                contact_service: FromDishka[ContactService],
                token: str = Depends(self._auth_api.oauth2_scheme)
        ):
            user_id = await self._auth_api.get_current_user(token)
            self._logger.info("User %s rejecting contact request from user %s",
                              user_id, request_data.receiver_id)

            check_contact = await contact_service.get_contact_requests(
                contact=ContactRequestDTO(
                    sender_id=request_data.receiver_id,
                    receiver_id=user_id,
                ),
                is_all=False
            )

            if check_contact is None:
                self._logger.warning("Contact request not found from user %s to %s",
                                     request_data.receiver_id, user_id)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Contact request not found"
                )

            if check_contact.status == "rejected":
                self._logger.info("Contact request already rejected from user %s to %s",
                                  request_data.receiver_id, user_id)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Contact request is already {check_contact.status}"
                )

            self._logger.debug("Rejecting contact request (previous status: %s)", check_contact.status)
            contact = await contact_service.update_contact_request(
                contact=ContactRequestDTO(
                    sender_id=user_id,
                    receiver_id=request_data.receiver_id,
                    status="rejected"
                )
            )

            if not contact:
                self._logger.error("Failed to reject contact request from user %s to %s",
                                   user_id, request_data.receiver_id)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to reject contact request"
                )

            self._logger.info("Contact request rejected successfully from user %s to %s",
                              user_id, request_data.receiver_id)
            return {"status": "success reject contact request"}