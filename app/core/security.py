"""Security utilities including signature validation and encryption."""
import hashlib
import hmac
import base64
from typing import Optional

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

from app.core.settings import settings

ACCESS_KEY = settings.woa_config_app_id
SECRET_KEY = settings.woa_config_app_key


def get_signature(data: str, secret: str) -> str:
    """Generate HMAC-SHA256 signature."""
    mac = hmac.new(secret.encode("utf-8"), data.encode("utf-8"), hashlib.sha256)
    return base64.urlsafe_b64encode(mac.digest()).decode("utf-8").rstrip("=")


def md5_hash(s: str) -> str:
    """Generate MD5 hash."""
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def auth_check(event: dict) -> bool:
    """Validate event signature."""
    content = f"{ACCESS_KEY}:{event['topic']}:{event['nonce']}:{event['time']}:{event['encrypted_data']}"
    signature = get_signature(content, SECRET_KEY)
    return event["signature"] == signature


def decrypt_aes_cbc(encrypted_data: str, cipher: str, nonce: str) -> Optional[str]:
    """Decrypt AES-CBC encrypted data."""
    try:
        key = cipher.encode("utf-8")
        iv = nonce.encode("utf-8")[:16]
        encrypted_bytes = base64.b64decode(encrypted_data)
        
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        decryptor = cipher.decryptor()
        decrypted = decryptor.update(encrypted_bytes) + decryptor.finalize()
        
        padding_length = decrypted[-1]
        return decrypted[:-padding_length].decode("utf-8")
    except Exception as e:
        print(f"Decryption error: {e}")
        return None


def decrypt_event(event: dict) -> Optional[str]:
    """Decrypt event data."""
    try:
        cipher = md5_hash(SECRET_KEY)
        return decrypt_aes_cbc(event["encrypted_data"], cipher, event["nonce"])
    except Exception as e:
        print(f"Decryption error: {e}")
        return None
