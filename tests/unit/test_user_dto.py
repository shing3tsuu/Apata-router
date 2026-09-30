import pytest
from pydantic import ValidationError

from src.application.models.user import PublicKeyUpdateDTO, UserRegisterRequest

VALID_PEM_PUBLIC_KEY = (
    "-----BEGIN PUBLIC KEY-----\nkey-material\n-----END PUBLIC KEY-----"
)


def test_accepts_pem_public_keys() -> None:
    user = UserRegisterRequest(
        username="apata_user",
        ed_public_key=VALID_PEM_PUBLIC_KEY,
        ecdh_public_key=VALID_PEM_PUBLIC_KEY,
    )

    assert user.ed_public_key == VALID_PEM_PUBLIC_KEY


@pytest.mark.parametrize("field", ["ed_public_key", "ecdh_public_key"])
def test_rejects_non_pem_public_key(field: str) -> None:
    with pytest.raises(ValidationError, match="Invalid public key format"):
        PublicKeyUpdateDTO(**{field: "not-a-pem-key"})
