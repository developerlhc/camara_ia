import base64
import hashlib
import hmac
import json
import os

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from vigilay.config import settings

hasher = PasswordHasher()
DUMMY_HASH = hasher.hash("vigilay-dummy-constant-timing-password")


def hash_token(token: str):
    return hashlib.sha256(token.encode()).hexdigest()


def verify_password(encoded: str, password: str):
    try:
        return hasher.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False


def csrf_token(session_token: str):
    return hmac.new(
        settings().session_secret.encode(), session_token.encode(), "sha256"
    ).hexdigest()


def frigate_gateway_token(tenant_id: str, site_id: str) -> str:
    """Derive a per-site credential without persisting its clear text in MySQL."""
    digest = hmac.new(
        settings().internal_proxy_secret.encode(),
        f"frigate-gateway:{tenant_id}:{site_id}".encode(),
        "sha256",
    ).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def encrypt_credentials(data: dict, tenant_id: str, camera_id: str):
    nonce = os.urandom(12)
    key = base64.b64decode(settings().credential_encryption_key)
    context = f"vigilay:{tenant_id}:{camera_id}".encode()
    return nonce + AESGCM(key).encrypt(nonce, json.dumps(data).encode(), context)


def decrypt_credentials(value: bytes, tenant_id: str, camera_id: str):
    key = base64.b64decode(settings().credential_encryption_key)
    context = f"vigilay:{tenant_id}:{camera_id}".encode()
    return json.loads(AESGCM(key).decrypt(value[:12], value[12:], context))
