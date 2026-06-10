import hashlib
import hmac
import base64
from typing import Optional


ACCESS_KEY = "AK20260520ZSVODH"
SECRET_KEY = "SKpmrxtgmbrhwtyc"
IV = b"0000000000000000"


def get_signature(data: str, secret: str) -> str:
    mac = hmac.new(secret.encode("utf-8"), data.encode("utf-8"), hashlib.sha256)
    return base64.urlsafe_b64encode(mac.digest()).decode("utf-8").rstrip("=")


def md5_hash(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def auth_check(event: dict) -> bool:
    content = f"{ACCESS_KEY}:{event['topic']}:{event['nonce']}:{event['time']}:{event['encrypted_data']}"
    signature = get_signature(content, SECRET_KEY)
    return event["signature"] == signature


def decrypt_aes_cbc(encrypted_data: str, cipher: str, nonce: str) -> Optional[str]:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend
    
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


def encrypt(event: dict) -> Optional[str]:
    try:
        cipher = md5_hash(SECRET_KEY)
        return decrypt_aes_cbc(event["encrypted_data"], cipher, event["nonce"])
    except Exception as e:
        print(f"Encryption error: {e}")
        return None
