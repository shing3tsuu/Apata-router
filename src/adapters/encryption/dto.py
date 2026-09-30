from enum import Enum


class SignatureAlgorithmEnum(str, Enum):
    ED25519 = "ED-25519"
    ECDSA_SECP256R1 = "ECDSA-SECP256R1"
