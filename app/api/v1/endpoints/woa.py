"""WOA callback endpoint for receiving events."""
import json
import traceback
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session

from app.core.security import auth_check, decrypt_event
from app.core.database import get_db
from app.core.logging import logger
from app.services.agent import RAGAgent
from app.services.woa import WoaService
from app.services.session import SessionService

router = APIRouter()


@router.post("/callback/eventmsg")
async def handle_event(request: Request, db: Session = Depends(get_db)):
    """Handle WOA event callback."""
    session_service = SessionService(db)
    body = await request.body()
    event_data = body[:200] if len(body) > 200 else body
    logger.info(f"Received WOA event: {event_data}")
    
    try:
        event = json.loads(body.decode("utf-8"))
        topic = event.get("topic", "")
        operation = event.get("operation", "")
        chat_id = None
        user_id = None
        
        if "challenge" in event:
            logger.info("Returning challenge response")
            return event
        
        logger.info("Verifying signature...")
        if not auth_check(event):
            logger.warning("Signature verification failed")
            session_service.log_event(topic, operation, chat_id, user_id, str(body), "failed", "Invalid signature")
            raise HTTPException(status_code=401, detail="Invalid signature")
        
        logger.info("Signature OK, decrypting event data...")
        decrypted = decrypt_event(event)
        logger.debug(f"Decrypted data: {decrypted[:200] if decrypted else None}")
        
        if not decrypted:
            logger.warning("Decrypted data is empty")
            return event
        
        data = json.loads(decrypted)
        chat_id = data.get("chat", {}).get("id")
        user_id = data.get("sender", {}).get("id")
        message_text = data.get("message", {}).get("content", {}).get("text", {}).get("content")
        
        logger.info(f"Processing message - chat_id: {chat_id}, user_id: {user_id}, message: {message_text[:50] if message_text else None}")
        
        if not chat_id or not message_text:
            logger.warning("Missing chat_id or message_text")
            return event
        
        session = session_service.get_or_create_session(chat_id, user_id)
        session_service.add_message(session.id, event.get("message", {}).get("id", ""), "user", message_text)
        
        logger.info("Running LangGraph RAG Agent...")
        agent = RAGAgent(db, session_id=chat_id or "woa")
        answer = await agent.run(message_text)
        logger.info(f"Agent response: {answer[:50] if answer else None}")
        
        session_service.add_message(session.id, str(hash(answer)), "assistant", answer)
        
        logger.info("Sending response via WOA...")
        woa = WoaService()
        success = await woa.send_message(chat_id, answer)
        logger.info(f"Message sent successfully: {success}")
        
        session_service.log_event(topic, operation, chat_id, user_id, str(body), "success")
        return event
    
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error processing event: {error_msg}")
        session_service.log_event("", "", chat_id, user_id, str(body), "failed", error_msg)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_msg)
