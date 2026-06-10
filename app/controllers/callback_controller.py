from fastapi import APIRouter, Request, HTTPException
from app.utils.crypto import auth_check, encrypt
from app.services.deepseek_service import DeepSeekService
from app.services.woa_service import WoaService
import json

router = APIRouter()


@router.post("/callback/eventmsg")
async def event_callback(request: Request):
    try:
        json_str = await request.body()
        json_object = json.loads(json_str.decode("utf-8"))
        print(f"Received event: {json_object}")

        if "challenge" in json_object and json_object["challenge"]:
            return json_object

        if not auth_check(json_object):
            raise HTTPException(status_code=401, detail="签名不正确")

        encrypted = encrypt(json_object)
        print(f"Decrypted data: {encrypted}")

        if not encrypted:
            print("Decrypted data is empty")
            return json_object

        res_json = json.loads(encrypted)

        chat_json = res_json.get("chat")
        chat_id = chat_json.get("id") if chat_json else None

        message_json = res_json.get("message")
        content_json = message_json.get("content") if message_json else None
        text_json = content_json.get("text") if content_json else None
        issue = text_json.get("content") if text_json else None

        if not chat_id:
            print("chat.id is empty")
            return json_object

        if not issue:
            print("message.content.text.content is empty")
            return json_object

        print(f"chatId: {chat_id}, issue: {issue}")

        deepseek_service = DeepSeekService()
        answer = await deepseek_service.call_deepseek_model(issue)

        if not answer:
            answer = "模型调用失败"

        woa_service = WoaService()
        await woa_service.send_message(chat_id, answer)

        return json_object

    except Exception as e:
        print(f"Error processing event: {e}")
        raise HTTPException(status_code=500, detail=str(e))
