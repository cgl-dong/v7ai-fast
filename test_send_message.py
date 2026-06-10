import asyncio
import os
from dotenv import load_dotenv
from app.services.woa_service import WoaService

load_dotenv()

async def test_send_message():
    woa_service = WoaService()
    
    chat_id = "test_chat_id"
    content = "Hello from FastAPI test!"
    
    print(f"Testing send_message with chat_id: {chat_id}")
    print(f"Message content: {content}")
    
    success = await woa_service.send_message(chat_id, content)
    if success:
        print("✅ Message sent successfully")
    else:
        print("❌ Failed to send message")

if __name__ == "__main__":
    asyncio.run(test_send_message())
