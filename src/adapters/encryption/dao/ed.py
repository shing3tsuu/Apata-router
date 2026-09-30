import asyncio
import base64
import binascii

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519


class EDDAO:
    async def verify_ed25519_signature(
        self,
        public_key_pem: str,
        challenge: str,
        signature: str,
    ) -> bool:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            self._verify_ed25519_signature,
            public_key_pem,
            challenge,
            signature,
        )

    async def verify_ecdsa_secp256r1_signature(
        self,
        public_key_pem: str,
        challenge: str,
        signature: str,
    ) -> bool:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            self._verify_ecdsa_secp256r1_signature,
            public_key_pem,
            challenge,
            signature,
        )

    @staticmethod
    def _verify_ed25519_signature(
        public_key_pem: str,
        challenge: str,
        signature: str,
    ) -> bool:
        try:
            public_key = serialization.load_pem_public_key(
                public_key_pem.encode("ascii")
            )
            if not isinstance(public_key, ed25519.Ed25519PublicKey):
                return False

            public_key.verify(
                base64.b64decode(signature, validate=True),
                challenge.encode("utf-8"),
            )
        except (
            InvalidSignature,
            UnsupportedAlgorithm,
            ValueError,
            TypeError,
            UnicodeEncodeError,
            binascii.Error,
        ):
            return False
        return True

    @staticmethod
    def _verify_ecdsa_secp256r1_signature(
        public_key_pem: str,
        challenge: str,
        signature: str,
    ) -> bool:
        try:
            public_key = serialization.load_pem_public_key(
                public_key_pem.encode("ascii")
            )
            if not (
                isinstance(public_key, ec.EllipticCurvePublicKey)
                and isinstance(public_key.curve, ec.SECP256R1)
            ):
                return False

            public_key.verify(
                base64.b64decode(signature, validate=True),
                challenge.encode("utf-8"),
                ec.ECDSA(hashes.SHA256()),
            )
        except (
            InvalidSignature,
            UnsupportedAlgorithm,
            ValueError,
            TypeError,
            UnicodeEncodeError,
            binascii.Error,
        ):
            return False
        return True
