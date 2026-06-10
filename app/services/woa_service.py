import os
import httpx
from datetime import datetime, timezone
import hashlib
import hmac
from typing import Optional, Dict


class WoaService:
    def __init__(self):
        self.woa_host = os.getenv("WOA_HOST", "https://im2.yungongplat.com:9000")
        self.app_id = os.getenv("WOA_CONFIG_APP_ID", "AK20260520ZSVODH")
        self.app_key = os.getenv("WOA_CONFIG_APP_KEY", "SKpmrxtgmbrhwtyc")
        self.token = None

    async def get_application_token(self) -> Optional[str]:
        url = f"{self.woa_host}/openapi/oauth2/token"
        client_secret = self._get_client_secret()
        
        data = {
            "grant_type": "client_credentials",
            "client_id": self.app_id,
            "client_secret": client_secret
        }

        print(f"Getting token from: {url}")
        print(f"Params: {data}")

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, data=data)
                print(f"Token response status: {response.status_code}")
                print(f"Token response body: {response.text}")
                
                if response.status_code == 200:
                    result = response.json()
                    token = result.get("access_token")
                    if token:
                        print(f"Successfully got token: {token[:20]}...")
                    return token
                else:
                    print(f"Failed to get token. Status: {response.status_code}, Body: {response.text}")
                    return None
            except Exception as e:
                print(f"Error getting token: {e}")
                return None

    def _get_client_secret(self) -> str:
        time = self._get_gmt_date_string()
        raw = f"{self.app_id}:{self.app_key}:{time}"
        sha256_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return f"SEC {sha256_hash};{time}"

    def _get_gmt_date_string(self) -> str:
        return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")

    def _kso_auth(self, uri: str, date: str, content_type: str, method: str, param: str) -> str:
        request_body = param.encode("utf-8") if param else b""

        sha256_hex = hashlib.sha256(request_body).hexdigest() if request_body else ""
        data_to_sign = f"KSO-1{method}{uri}{content_type}{date}{sha256_hex}"

        print(f"KSO Auth Debug:")
        print(f"  uri: {uri}")
        print(f"  date: {date}")
        print(f"  content_type: {content_type}")
        print(f"  method: {method}")
        print(f"  sha256_hex: {sha256_hex}")
        print(f"  data_to_sign: {data_to_sign}")

        mac = hmac.new(self.app_key.encode("utf-8"), data_to_sign.encode("utf-8"), hashlib.sha256)
        kso_signature = mac.hexdigest()

        print(f"  final signature: {kso_signature}")

        return f"KSO-1 {self.app_id}:{kso_signature}"

    async def send_message(self, chat_id: str, content: str) -> bool:
        token = await self.get_application_token()
        if not token:
            print("Failed to get application token")
            return False

        url = f"{self.woa_host}/openapi/v7/messages/create"
        uri = url.split("openapi")[1]
        date = self._get_gmt_date_string()

        msg_param = {"content": content, "type": "markdown"}
        data = {
            "type": "text",
            "receiver": {"receiver_id": chat_id, "type": "chat"},
            "content": {"text": msg_param}
        }

        import json
        param_str = json.dumps(data, separators=(',', ':'))
        kso_authorization = self._kso_auth(uri, date, "application/json", "POST", param_str)

        headers = {
            "X-Kso-Date": date,
            "Content-Type": "application/json",
            "X-Kso-Authorization": kso_authorization,
            "Authorization": f"Bearer {token}"
        }

        print(f"Send message params: {param_str}")
        print(f"KSO Authorization: {kso_authorization}")

        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, content=param_str.encode("utf-8"))
            print(f"Send message response: {response.status_code}")
            print(f"Send message response body: {response.text}")
            return response.status_code == 200
