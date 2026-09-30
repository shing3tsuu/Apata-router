import logging
from typing import Annotated
from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.adapters.database.dto import ContactDTO, CreateContactDTO, UserDTO
from src.adapters.database.service import ContactService, UserService
from src.adapters.database.structures import ContactStatusEnum
from src.adapters.encryption.service.jwt import JWTService
from src.adapters.realtime import RealtimePublisher
from src.application.models.contact import (
    AnswerContactRequest,
    ContactPageResponse,
    ContactPublicResponse,
    CreateContactRequest,
)
from src.errors.error import ContactAlreadyExistsError

from .user import AuthAPI

PAGE_SIZE = 50


def _status_for_user(contact: ContactDTO | None, current_user_id: UUID) -> str:
    if contact is None:
        return ContactStatusEnum.BLANK.value
    if contact.status is ContactStatusEnum.PENDING:
        if contact.sender_id == current_user_id:
            return "pending(outgoing)"
        return "pending(incoming)"
    if contact.status is ContactStatusEnum.BLACKLIST:
        if contact.sender_id == current_user_id:
            return ContactStatusEnum.BLACKLIST.value
        return ContactStatusEnum.BLANK.value
    return contact.status.value


def _contact_response(
    *,
    user: UserDTO,
    contact: ContactDTO | None,
    current_user_id: UUID,
) -> ContactPublicResponse:
    if user.ed_public_key is None or user.ecdh_public_key is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User has incomplete public keys",
        )

    can_view_presence = (
        contact is not None and contact.status is ContactStatusEnum.ACCEPTED
    )

    return ContactPublicResponse(
        contact_id=contact.id if contact is not None else None,
        user_id=user.id,
        username=user.username,
        ed_public_key=user.ed_public_key,
        ecdh_public_key=user.ecdh_public_key,
        status=_status_for_user(contact, current_user_id),
        online=user.online if can_view_presence else None,
        last_seen=user.last_seen if can_view_presence else None,
    )


class ContactAPI:
    def __init__(self) -> None:
        self._contact_router = APIRouter(prefix="/contacts", tags=["Contacts"])
        self._register_endpoints()

    def get_router(self) -> APIRouter:
        return self._contact_router

    def _register_endpoints(self) -> None:
        @self._contact_router.get("/search", response_model=ContactPageResponse)
        @inject
        async def search_contacts(
            username: Annotated[str, Query(min_length=2, max_length=50)],
            auth_api: FromDishka[AuthAPI],
            jwt_service: FromDishka[JWTService],
            user_service: FromDishka[UserService],
            contact_service: FromDishka[ContactService],
            logger: FromDishka[logging.Logger],
            token: str = Depends(AuthAPI.oauth2_scheme),
        ) -> ContactPageResponse:
            current_user_id = await auth_api.get_current_user(
                token, jwt_service, logger
            )
            users = await user_service.search_users_by_name(username=username)
            users = [user for user in users if user.id != current_user_id]

            contacts_by_user_id = await contact_service.get_contacts_between_users(
                current_user_id=current_user_id,
                other_user_ids=[user.id for user in users],
            )
            return ContactPageResponse(
                items=[
                    _contact_response(
                        user=user,
                        contact=contacts_by_user_id.get(user.id),
                        current_user_id=current_user_id,
                    )
                    for user in users
                ]
            )

        @self._contact_router.get("", response_model=ContactPageResponse)
        @inject
        async def list_contacts(
            auth_api: FromDishka[AuthAPI],
            jwt_service: FromDishka[JWTService],
            user_service: FromDishka[UserService],
            contact_service: FromDishka[ContactService],
            logger: FromDishka[logging.Logger],
            after_id: UUID | None = None,
            token: str = Depends(AuthAPI.oauth2_scheme),
        ) -> ContactPageResponse:
            current_user_id = await auth_api.get_current_user(
                token, jwt_service, logger
            )
            contacts = await contact_service.get_contacts_by_user_id(
                user_id=current_user_id,
                after_id=after_id,
                limit=PAGE_SIZE + 1,
            )
            has_next_page = len(contacts) > PAGE_SIZE
            visible_contacts = contacts[:PAGE_SIZE]

            other_user_ids = [
                contact.receiver_id
                if contact.sender_id == current_user_id
                else contact.sender_id
                for contact in visible_contacts
            ]
            users = await user_service.get_users_by_id(other_user_ids)
            assert isinstance(users, list)
            users_by_id = {user.id: user for user in users}

            items = []
            for contact in visible_contacts:
                other_user_id = (
                    contact.receiver_id
                    if contact.sender_id == current_user_id
                    else contact.sender_id
                )
                other_user = users_by_id.get(other_user_id)
                if other_user is not None:
                    items.append(
                        _contact_response(
                            user=other_user,
                            contact=contact,
                            current_user_id=current_user_id,
                        )
                    )

            return ContactPageResponse(
                items=items,
                next_after_id=visible_contacts[-1].id if has_next_page else None,
            )

        @self._contact_router.post(
            "",
            response_model=ContactPublicResponse,
            status_code=status.HTTP_201_CREATED,
        )
        @inject
        async def create_contact_request(
            request_data: CreateContactRequest,
            auth_api: FromDishka[AuthAPI],
            jwt_service: FromDishka[JWTService],
            user_service: FromDishka[UserService],
            contact_service: FromDishka[ContactService],
            realtime_publisher: FromDishka[RealtimePublisher],
            logger: FromDishka[logging.Logger],
            token: str = Depends(AuthAPI.oauth2_scheme),
        ) -> ContactPublicResponse:
            current_user_id = await auth_api.get_current_user(
                token, jwt_service, logger
            )
            if current_user_id == request_data.receiver_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot create a contact request to yourself",
                )

            receiver = await user_service.get_users_by_id(request_data.receiver_id)
            assert receiver is None or isinstance(receiver, UserDTO)
            if receiver is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Receiver user not found",
                )

            try:
                contact = await contact_service.add_contact_request(
                    CreateContactDTO(
                        sender_id=current_user_id,
                        receiver_id=receiver.id,
                        status=ContactStatusEnum.PENDING,
                    )
                )
            except ContactAlreadyExistsError as error:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=error.message,
                ) from error

            logger.info(
                "Contact request created: sender=%s receiver=%s",
                current_user_id,
                receiver.id,
            )
            await realtime_publisher.publish(
                "contact_changed",
                [current_user_id, receiver.id],
                {
                    "contact_id": str(contact.id),
                    "actor_id": str(current_user_id),
                    "user_id": str(receiver.id),
                    "action": "request_created",
                },
            )
            return _contact_response(
                user=receiver,
                contact=contact,
                current_user_id=current_user_id,
            )

        @self._contact_router.put(
            "/{user_id}/blacklist",
            response_model=ContactPublicResponse,
        )
        @inject
        async def blacklist_contact(
            user_id: UUID,
            auth_api: FromDishka[AuthAPI],
            jwt_service: FromDishka[JWTService],
            user_service: FromDishka[UserService],
            contact_service: FromDishka[ContactService],
            realtime_publisher: FromDishka[RealtimePublisher],
            logger: FromDishka[logging.Logger],
            token: str = Depends(AuthAPI.oauth2_scheme),
        ) -> ContactPublicResponse:
            current_user_id = await auth_api.get_current_user(
                token, jwt_service, logger
            )
            if current_user_id == user_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot blacklist yourself",
                )

            blocked_user = await user_service.get_users_by_id(user_id)
            assert blocked_user is None or isinstance(blocked_user, UserDTO)
            if blocked_user is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User to blacklist not found",
                )

            contact = await contact_service.blacklist_contact(
                blocker_id=current_user_id,
                blocked_user_id=blocked_user.id,
            )
            logger.info(
                "User blacklisted: blocker=%s blocked=%s",
                current_user_id,
                blocked_user.id,
            )
            await realtime_publisher.publish(
                "contact_changed",
                [current_user_id, blocked_user.id],
                {
                    "contact_id": str(contact.id),
                    "actor_id": str(current_user_id),
                    "user_id": str(blocked_user.id),
                    "action": "blacklisted",
                },
            )
            return _contact_response(
                user=blocked_user,
                contact=contact,
                current_user_id=current_user_id,
            )

        @self._contact_router.patch(
            "/{contact_id}",
            response_model=ContactPublicResponse,
        )
        @inject
        async def answer_contact_request(
            contact_id: UUID,
            request_data: AnswerContactRequest,
            auth_api: FromDishka[AuthAPI],
            jwt_service: FromDishka[JWTService],
            user_service: FromDishka[UserService],
            contact_service: FromDishka[ContactService],
            realtime_publisher: FromDishka[RealtimePublisher],
            logger: FromDishka[logging.Logger],
            token: str = Depends(AuthAPI.oauth2_scheme),
        ) -> ContactPublicResponse:
            current_user_id = await auth_api.get_current_user(
                token, jwt_service, logger
            )
            contact = await contact_service.get_contact_by_id(contact_id)
            if contact is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Contact request not found",
                )
            if contact.receiver_id != current_user_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only the contact request receiver can answer it",
                )
            if contact.status is not ContactStatusEnum.PENDING:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Contact request is not pending",
                )

            sender = await user_service.get_users_by_id(contact.sender_id)
            assert sender is None or isinstance(sender, UserDTO)
            if sender is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Contact request sender not found",
                )

            if request_data.action == "accept":
                updated_contact = await contact_service.update_contact_request(
                    contact_id=contact.id,
                    status=ContactStatusEnum.ACCEPTED,
                )
                assert updated_contact is not None
                logger.info("Contact request accepted: contact=%s", contact.id)
                await realtime_publisher.publish(
                    "contact_changed",
                    [contact.sender_id, contact.receiver_id],
                    {
                        "contact_id": str(contact.id),
                        "actor_id": str(current_user_id),
                        "user_id": str(contact.sender_id),
                        "action": "accepted",
                    },
                )
                return _contact_response(
                    user=sender,
                    contact=updated_contact,
                    current_user_id=current_user_id,
                )

            deleted = await contact_service.delete_contact_request(contact.id)
            assert deleted
            logger.info("Contact request rejected: contact=%s", contact.id)
            await realtime_publisher.publish(
                "contact_changed",
                [contact.sender_id, contact.receiver_id],
                {
                    "contact_id": str(contact.id),
                    "actor_id": str(current_user_id),
                    "user_id": str(contact.sender_id),
                    "action": "rejected",
                },
            )
            return _contact_response(
                user=sender,
                contact=None,
                current_user_id=current_user_id,
            )
