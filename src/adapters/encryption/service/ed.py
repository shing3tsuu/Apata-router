from ..dao.ed import EDDAO
from ..dto import SignatureAlgorithmEnum


class EDService:
    def __init__(self, ed_dao: EDDAO) -> None:
        self._ed_dao = ed_dao

    async def verify_signature(
        self,
        algorithm: str,
        public_key_pem: str,
        challenge: str,
        signature: str,
    ) -> bool:
        try:
            signature_algorithm = SignatureAlgorithmEnum(algorithm)
        except (TypeError, ValueError):
            return False

        if signature_algorithm is SignatureAlgorithmEnum.ED25519:
            return await self._ed_dao.verify_ed25519_signature(
                public_key_pem,
                challenge,
                signature,
            )

        if signature_algorithm is SignatureAlgorithmEnum.ECDSA_SECP256R1:
            return await self._ed_dao.verify_ecdsa_secp256r1_signature(
                public_key_pem,
                challenge,
                signature,
            )

        return False
