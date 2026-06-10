"""Web UI endpoints for chat and admin panel."""
from fastapi import APIRouter, Request, Depends
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import datetime

from app.core.database import get_db, init_db
from app.services.session import SessionService
from app.services.deepseek import DeepSeekService

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/chat")
async def chat_page(request: Request):
    """Chat interface page."""
    return templates.TemplateResponse("chat.html", {"request": request})


@router.post("/api/chat")
async def chat_message(request: Request, db: Session = Depends(get_db)):
    """Handle chat message."""
    data = await request.json()
    message = data.get("message", "")
    session_id = data.get("session_id", "web-" + str(datetime.now().timestamp()))
    
    session_service = SessionService(db)
    session = session_service.get_or_create_session(session_id)
    session_service.add_message(session.id, str(datetime.now().timestamp()), "user", message)
    
    deepseek = DeepSeekService()
    answer = await deepseek.call_model(message)
    
    session_service.add_message(session.id, str(datetime.now().timestamp()), "assistant", answer)
    
    return {"response": answer, "session_id": session_id}


@router.get("/admin")
async def admin_panel(request: Request, db: Session = Depends(get_db)):
    """Admin panel page."""
    session_service = SessionService(db)
    sessions = session_service.get_sessions()
    events = session_service.get_recent_events()
    
    return templates.TemplateResponse("admin.html", {
        "request": request,
        "sessions": sessions,
        "events": events
    })


@router.get("/admin/session/{chat_id}")
async def session_detail(request: Request, chat_id: str, db: Session = Depends(get_db)):
    """Session detail page."""
    session_service = SessionService(db)
    messages = session_service.get_session_messages(chat_id)
    
    return templates.TemplateResponse("session_detail.html", {
        "request": request,
        "chat_id": chat_id,
        "messages": messages
    })


@router.get("/init-db")
async def init_database():
    """Initialize the database."""
    init_db()
    return {"message": "Database initialized successfully"}
