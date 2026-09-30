import base64
import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from dishka import make_async_container

from src.adapters.encryption.dto import SignatureAlgorithmEnum
from src.adapters.encryption.service.ed import EDService
from src.providers import AppProvider


@pytest_asyncio.fixture
async def ed_service() -> AsyncIterator[EDService]:
    container = make_async_container(AppProvider())
    try:
        async with container() as request_container:
            yield await request_container.get(EDService)
    finally:
        await container.close()


@pytest.fixture
def ed25519_signature() -> tuple[str, str, str]:
    challenge = "ed25519 challenge"
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key_pem = (
        private_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )
    signature = base64.b64encode(private_key.sign(challenge.encode("utf-8"))).decode(
        "ascii"
    )
    return public_key_pem, challenge, signature


@pytest.fixture
def secp256r1_signature() -> tuple[str, str, str]:
    challenge = "secp256r1 challenge"
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key_pem = (
        private_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )
    signature = base64.b64encode(
        private_key.sign(challenge.encode("utf-8"), ec.ECDSA(hashes.SHA256()))
    ).decode("ascii")
    return public_key_pem, challenge, signature


@pytest.mark.asyncio
async def test_verify_ed25519_signature(
    ed_service: EDService,
    ed25519_signature: tuple[str, str, str],
) -> None:
    public_key_pem, challenge, signature = ed25519_signature

    assert await ed_service.verify_signature(
        SignatureAlgorithmEnum.ED25519.value,
        public_key_pem,
        challenge,
        signature,
    )


@pytest.mark.asyncio
async def test_verify_secp256r1_signature(
    ed_service: EDService,
    secp256r1_signature: tuple[str, str, str],
) -> None:
    public_key_pem, challenge, signature = secp256r1_signature

    assert await ed_service.verify_signature(
        SignatureAlgorithmEnum.ECDSA_SECP256R1.value,
        public_key_pem,
        challenge,
        signature,
    )


@pytest.mark.asyncio
async def test_reject_invalid_signature(
    ed_service: EDService,
    ed25519_signature: tuple[str, str, str],
) -> None:
    public_key_pem, challenge, _ = ed25519_signature
    invalid_signature = base64.b64encode(os.urandom(64)).decode("ascii")

    assert not await ed_service.verify_signature(
        SignatureAlgorithmEnum.ED25519.value,
        public_key_pem,
        challenge,
        invalid_signature,
    )


@pytest.mark.asyncio
async def test_reject_unsupported_signature_algorithm(
    ed_service: EDService,
    ed25519_signature: tuple[str, str, str],
) -> None:
    public_key_pem, challenge, signature = ed25519_signature

    assert not await ed_service.verify_signature(
        "RSA-4096",
        public_key_pem,
        challenge,
        signature,
    )
