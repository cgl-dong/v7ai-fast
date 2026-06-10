import asyncio
import os
from dotenv import load_dotenv
from app.services.woa_service import WoaService

load_dotenv()

async def test_token():
    woa_service = WoaService()
    print(f"WOA Host: {woa_service.woa_host}")
    print(f"App ID: {woa_service.app_id}")
    print(f"App Key: {woa_service.app_key}")
    
    token = await woa_service.get_application_token()
    if token:
        print(f"✅ Token obtained successfully: {token}")
    else:
        print("❌ Failed to get token")

if __name__ == "__main__":
    asyncio.run(test_token())
