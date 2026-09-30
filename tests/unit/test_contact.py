from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.routing import APIRoute
from pydantic import ValidationError
from sqlalchemy.orm import configure_mappers

from src.adapters.database.dao.contact import ContactDAO
from src.adapters.database.dao.user import UserDAO
from src.adapters.database.dto import (
    ContactDTO,
    CreateChatDTO,
    CreateContactDTO,
    UserDTO,
)
from src.adapters.database.service.contact import ContactService
from src.adapters.database.structures import ContactStatusEnum
from src.application.routers.contact import (
    ContactAPI,
    _contact_response,
    _status_for_user,
)


def test_contact_mappers_configure() -> None:
    configure_mappers()


def test_contact_request_defaults_to_blank() -> None:
    contact = CreateContactDTO(sender_id=uuid4(), receiver_id=uuid4())

    assert contact.status is ContactStatusEnum.BLANK


def test_contact_request_rejects_the_same_user() -> None:
    user_id = uuid4()

    with pytest.raises(ValidationError, match="cannot create a contact request"):
        CreateContactDTO(sender_id=user_id, receiver_id=user_id)


def test_chat_name_is_normalized_and_cannot_be_blank() -> None:
    chat = CreateChatDTO(owner_id=uuid4(), name="  Group chat  ")

    assert chat.name == "Group chat"

    with pytest.raises(ValidationError, match="Chat name cannot be blank"):
        CreateChatDTO(owner_id=uuid4(), name="   ")


async def test_get_contact_request_returns_none_when_absent() -> None:
    session = AsyncMock()
    session.scalar.return_value = None
    dao = ContactDAO(session)

    contact = await dao.get_contact_request(uuid4(), uuid4())

    assert contact is None


async def test_global_user_search_has_no_result_limit() -> None:
    session = AsyncMock()
    session.scalars.return_value = []
    dao = UserDAO(session)

    users = await dao.search_users_by_name("ghost")

    statement = session.scalars.await_args.args[0]
    assert users == []
    assert statement._limit_clause is None


def test_pending_status_is_derived_for_the_viewing_user() -> None:
    sender_id = uuid4()
    receiver_id = uuid4()
    contact = ContactDTO(
        id=uuid4(),
        sender_id=sender_id,
        receiver_id=receiver_id,
        status=ContactStatusEnum.PENDING,
        created_at=datetime.now(UTC),
    )

    assert _status_for_user(contact, sender_id) == "pending(outgoing)"
    assert _status_for_user(contact, receiver_id) == "pending(incoming)"


def test_blacklist_status_is_visible_only_to_the_blocker() -> None:
    blocker_id = uuid4()
    blocked_user_id = uuid4()
    contact = ContactDTO(
        id=uuid4(),
        sender_id=blocker_id,
        receiver_id=blocked_user_id,
        status=ContactStatusEnum.BLACKLIST,
        created_at=datetime.now(UTC),
    )

    assert _status_for_user(contact, blocker_id) == "blacklist"
    assert _status_for_user(contact, blocked_user_id) == "blank"


async def test_contact_request_promotes_blank_relation_and_sets_direction() -> None:
    requester_id = uuid4()
    receiver_id = uuid4()
    existing = ContactDTO(
        id=uuid4(),
        sender_id=receiver_id,
        receiver_id=requester_id,
        status=ContactStatusEnum.BLANK,
        created_at=datetime.now(UTC),
    )
    updated = existing.model_copy(
        update={
            "sender_id": requester_id,
            "receiver_id": receiver_id,
            "status": ContactStatusEnum.PENDING,
        }
    )
    contact_dao = AsyncMock(spec=ContactDAO)
    contact_dao.get_contact_between_users.return_value = existing
    contact_dao.update_contact_relation.return_value = updated
    common_dao = AsyncMock()
    service = ContactService(contact_dao, common_dao)

    result = await service.add_contact_request(
        CreateContactDTO(
            sender_id=requester_id,
            receiver_id=receiver_id,
            status=ContactStatusEnum.PENDING,
        )
    )

    assert result == updated
    relation = contact_dao.update_contact_relation.await_args.kwargs["contact"]
    assert relation.sender_id == requester_id
    assert relation.receiver_id == receiver_id
    assert relation.status is ContactStatusEnum.PENDING


async def test_blacklist_contact_creates_directional_relation() -> None:
    blocker_id = uuid4()
    blocked_user_id = uuid4()
    created = ContactDTO(
        id=uuid4(),
        sender_id=blocker_id,
        receiver_id=blocked_user_id,
        status=ContactStatusEnum.BLACKLIST,
        created_at=datetime.now(UTC),
    )
    contact_dao = AsyncMock(spec=ContactDAO)
    contact_dao.get_contact_between_users.return_value = None
    contact_dao.add_contact_request.return_value = created
    common_dao = AsyncMock()
    service = ContactService(contact_dao, common_dao)

    result = await service.blacklist_contact(blocker_id, blocked_user_id)

    assert result == created
    relation = contact_dao.add_contact_request.await_args.args[0]
    assert relation.sender_id == blocker_id
    assert relation.receiver_id == blocked_user_id
    assert relation.status is ContactStatusEnum.BLACKLIST


@pytest.mark.parametrize(
    "contact_status",
    [
        None,
        ContactStatusEnum.BLANK,
        ContactStatusEnum.PENDING,
        ContactStatusEnum.BLACKLIST,
    ],
)
def test_presence_is_hidden_from_non_friends(
    contact_status: ContactStatusEnum | None,
) -> None:
    current_user_id = uuid4()
    other_user = UserDTO(
        id=uuid4(),
        username="ghost",
        ed_public_key="ed-public-key",
        ecdh_public_key="ecdh-public-key",
        ecdh_signature=None,
        last_seen=datetime.now(UTC),
        online=True,
    )
    contact = (
        ContactDTO(
            id=uuid4(),
            sender_id=current_user_id,
            receiver_id=other_user.id,
            status=contact_status,
            created_at=datetime.now(UTC),
        )
        if contact_status is not None
        else None
    )

    response = _contact_response(
        user=other_user,
        contact=contact,
        current_user_id=current_user_id,
    )

    assert response.online is None
    assert response.last_seen is None


def test_presence_is_visible_to_accepted_friends() -> None:
    current_user_id = uuid4()
    last_seen = datetime.now(UTC)
    other_user = UserDTO(
        id=uuid4(),
        username="ghost",
        ed_public_key="ed-public-key",
        ecdh_public_key="ecdh-public-key",
        ecdh_signature=None,
        last_seen=last_seen,
        online=True,
    )
    contact = ContactDTO(
        id=uuid4(),
        sender_id=current_user_id,
        receiver_id=other_user.id,
        status=ContactStatusEnum.ACCEPTED,
        created_at=datetime.now(UTC),
    )

    response = _contact_response(
        user=other_user,
        contact=contact,
        current_user_id=current_user_id,
    )

    assert response.online is True
    assert response.last_seen == last_seen


def test_contact_api_routes_match_the_client_contract() -> None:
    api = ContactAPI()
    routes = {
        (route.path, tuple(sorted(route.methods or set())))
        for route in api.get_router().routes
        if isinstance(route, APIRoute)
    }

    assert ("/contacts/search", ("GET",)) in routes
    assert ("/contacts", ("GET",)) in routes
    assert ("/contacts", ("POST",)) in routes
    assert ("/contacts/{user_id}/blacklist", ("PUT",)) in routes
    assert ("/contacts/{contact_id}", ("PATCH",)) in routes
