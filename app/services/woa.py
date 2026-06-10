"""WOA service for authentication and message sending."""
import httpx
import hashlib
import hmac
from datetime import datetime, timezone
from typing import Optional

from app.core.settings import settings


class WoaService:
    """Service for interacting with WOA platform."""
    
    def __init__(self):
        self.woa_host = settings.woa_host
        self.app_id = settings.woa_config_app_id
        self.app_key = settings.woa_config_app_key
    
    async def get_token(self) -> Optional[str]:
        """Get application access token from WOA."""
        url = f"{self.woa_host}/openapi/oauth2/token"
        client_secret = self._generate_client_secret()
        
        data = {
            "grant_type": "client_credentials",
            "client_id": self.app_id,
            "client_secret": client_secret
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, data=data)
            if response.status_code == 200:
                return response.json().get("access_token")
            return None
    
    def _generate_client_secret(self) -> str:
        """Generate client secret for token request."""
        time = self._get_gmt_time()
        raw = f"{self.app_id}:{self.app_key}:{time}"
        sha256_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return f"SEC {sha256_hash};{time}"
    
    def _get_gmt_time(self) -> str:
        """Get current time in GMT format."""
        return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
    
    def _generate_kso_signature(self, uri: str, date: str, content_type: str, 
                               method: str, body: str) -> str:
        """Generate KSO-1 signature."""
        request_body = body.encode("utf-8") if body else b""
        sha256_hex = hashlib.sha256(request_body).hexdigest()
        data_to_sign = f"KSO-1{method}{uri}{content_type}{date}{sha256_hex}"
        
        mac = hmac.new(self.app_key.encode("utf-8"), data_to_sign.encode("utf-8"), hashlib.sha256)
        signature = mac.hexdigest()
        
        return f"KSO-1 {self.app_id}:{signature}"
    
    async def send_message(self, chat_id: str, content: str) -> bool:
        """Send message to WOA chat."""
        token = await self.get_token()
        if not token:
            return False
        
        url = f"{self.woa_host}/openapi/v7/messages/create"
        uri = url.split("openapi")[1]
        date = self._get_gmt_time()
        
        import json
        data = {
            "type": "text",
            "receiver": {"receiver_id": chat_id, "type": "chat"},
            "content": {"text": {"content": content, "type": "markdown"}}
        }
        
        body = json.dumps(data, separators=(',', ':'))
        kso_auth = self._generate_kso_signature(uri, date, "application/json", "POST", body)
        
        headers = {
            "X-Kso-Date": date,
            "Content-Type": "application/json",
            "X-Kso-Authorization": kso_auth,
            "Authorization": f"Bearer {token}"
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, content=body.encode("utf-8"))
            return response.status_code == 200
