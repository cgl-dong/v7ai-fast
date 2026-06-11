"""Web UI endpoints for chat and admin panel."""
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from datetime import datetime
import os

from app.core.database import get_db, init_db
from app.core.database import ChatMessage
from app.core.logging import logger
from app.services.session import SessionService
from app.services.deepseek import DeepSeekService
from app.services.auth import AuthService

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    """Login page."""
    html_content = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>v7ai-fast - Login</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; display: flex; align-items: center; justify-content: center; }
        .login-container { background: white; border-radius: 16px; padding: 40px; box-shadow: 0 10px 40px rgba(0,0,0,0.2); width: 400px; }
        .login-container h1 { text-align: center; color: #333; margin-bottom: 30px; font-size: 28px; }
        .form-group { margin-bottom: 20px; }
        .form-group label { display: block; margin-bottom: 8px; color: #555; font-weight: 500; }
        .form-group input { width: 100%; padding: 12px 16px; border: 1px solid #ddd; border-radius: 8px; font-size: 16px; outline: none; transition: border-color 0.3s; }
        .form-group input:focus { border-color: #667eea; }
        .btn { width: 100%; padding: 14px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border: none; border-radius: 8px; font-size: 16px; cursor: pointer; margin-top: 20px; }
        .btn:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(102,126,234,0.4); }
        .toggle-form { text-align: center; margin-top: 20px; color: #666; }
        .toggle-form a { color: #667eea; text-decoration: none; }
        .error-message { background: #f8d7da; color: #721c24; padding: 10px; border-radius: 6px; margin-bottom: 15px; display: none; }
        .success-message { background: #d4edda; color: #155724; padding: 10px; border-radius: 6px; margin-bottom: 15px; display: none; }
    </style>
</head>
<body>
    <div class="login-container">
        <h1>🤖 v7ai-fast</h1>
        <div class="error-message" id="error-message"></div>
        <div class="success-message" id="success-message"></div>
        
        <form id="login-form">
            <div class="form-group">
                <label>用户名</label>
                <input type="text" id="username" placeholder="请输入用户名" required>
            </div>
            <div class="form-group">
                <label>密码</label>
                <input type="password" id="password" placeholder="请输入密码" required>
            </div>
            <button type="submit" class="btn">登录</button>
        </form>
        
        <div class="toggle-form">
            还没有账号？<a href="#" onclick="showRegister()">立即注册</a>
        </div>
    </div>

    <div class="login-container" id="register-container" style="display: none;">
        <h1>🤖 v7ai-fast</h1>
        <div class="error-message" id="register-error"></div>
        <div class="success-message" id="register-success"></div>
        
        <form id="register-form">
            <div class="form-group">
                <label>用户名</label>
                <input type="text" id="reg-username" placeholder="请输入用户名" required>
            </div>
            <div class="form-group">
                <label>邮箱（可选）</label>
                <input type="email" id="reg-email" placeholder="请输入邮箱">
            </div>
            <div class="form-group">
                <label>密码</label>
                <input type="password" id="reg-password" placeholder="请输入密码" required>
            </div>
            <button type="submit" class="btn">注册</button>
        </form>
        
        <div class="toggle-form">
            已有账号？<a href="#" onclick="showLogin()">立即登录</a>
        </div>
    </div>

    <script>
        function showRegister() {
            document.querySelector('.login-container').style.display = 'none';
            document.getElementById('register-container').style.display = 'block';
        }
        
        function showLogin() {
            document.getElementById('register-container').style.display = 'none';
            document.querySelector('.login-container').style.display = 'block';
        }
        
        document.getElementById('login-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const username = document.getElementById('username').value;
            const password = document.getElementById('password').value;
            
            const formData = new FormData();
            formData.append('username', username);
            formData.append('password', password);
            
            const response = await fetch('/api/v1/auth/token', {
                method: 'POST',
                body: formData
            });
            
            if (response.ok) {
                const data = await response.json();
                localStorage.setItem('token', data.access_token);
                localStorage.setItem('username', data.username);
                window.location.href = '/chat';
            } else {
                document.getElementById('error-message').textContent = '登录失败：用户名或密码错误';
                document.getElementById('error-message').style.display = 'block';
            }
        });
        
        document.getElementById('register-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const username = document.getElementById('reg-username').value;
            const email = document.getElementById('reg-email').value;
            const password = document.getElementById('reg-password').value;
            
            try {
                const response = await fetch(`/api/v1/auth/register?username=${encodeURIComponent(username)}&password=${encodeURIComponent(password)}&email=${encodeURIComponent(email)}`, {
                    method: 'POST'
                });
                
                if (response.ok) {
                    document.getElementById('register-success').textContent = '注册成功！请登录';
                    document.getElementById('register-success').style.display = 'block';
                    setTimeout(() => showLogin(), 2000);
                } else {
                    const data = await response.json();
                    const errorMsg = data.detail || '注册失败，请重试';
                    document.getElementById('register-error').textContent = '注册失败：' + errorMsg;
                    document.getElementById('register-error').style.display = 'block';
                }
            } catch (error) {
                document.getElementById('register-error').textContent = '注册失败：网络错误，请重试';
                document.getElementById('register-error').style.display = 'block';
            }
        });
    </script>
</body>
</html>
    """
    return HTMLResponse(content=html_content)


@router.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request, db: Session = Depends(get_db)):
    """Chat interface page with session list."""
    session_service = SessionService(db)
    sessions = session_service.get_sessions(limit=50)
    
    sessions_html = ""
    for s in sessions:
        chat_id = s.chat_id or "unknown"
        sessions_html += '<div class="session-item" onclick="loadSession(\'' + chat_id + '\')" data-session-id="' + chat_id + '">\n'
        sessions_html += '    <div class="session-title">' + (chat_id[:20] + ('...' if len(chat_id) > 20 else '')) + '</div>\n'
        sessions_html += '    <div class="session-time">' + s.created_at.strftime('%m-%d %H:%M') + '</div>\n'
        sessions_html += '</div>\n'
    
    with open('templates/chat_full.html', 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    html_content = html_content.replace('{{ sessions_html }}', sessions_html)
    return HTMLResponse(content=html_content)


@router.get("/api/get-sessions")
async def get_sessions(db: Session = Depends(get_db)):
    """Get all chat sessions with message preview."""
    session_service = SessionService(db)
    sessions = session_service.get_sessions(limit=50)

    result = []
    for s in sessions:
        # 取第一条消息作为会话预览
        messages = db.query(ChatMessage)\
            .filter(ChatMessage.session_id == s.id)\
            .order_by(ChatMessage.created_at)\
            .limit(1)\
            .all()
        preview = messages[0].content[:50] + ("..." if len(messages[0].content) > 50 else "") if messages else "新对话"
        result.append({
            "chat_id": s.chat_id,
            "preview": preview,
            "time": s.created_at.strftime('%m-%d %H:%M')
        })

    return {"sessions": result}


@router.get("/api/get-messages")
async def get_messages(session_id: str, db: Session = Depends(get_db)):
    """Get messages for a session."""
    session_service = SessionService(db)
    messages = session_service.get_session_messages(session_id)
    
    result = []
    for msg in messages:
        result.append({
            "role": msg.role,
            "content": msg.content,
            "time": msg.created_at.strftime('%Y-%m-%d %H:%M:%S')
        })
    
    return {"messages": result}


@router.post("/api/create-session")
async def create_session(db: Session = Depends(get_db)):
    """Create a new empty chat session."""
    session_service = SessionService(db)
    session_id = "web-" + str(datetime.now().timestamp())
    session = session_service.get_or_create_session(session_id)
    return {"session_id": session.chat_id}


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


@router.get("/admin", response_class=HTMLResponse)
async def admin_panel(request: Request, db: Session = Depends(get_db)):
    """Admin panel page."""
    session_service = SessionService(db)
    sessions = session_service.get_sessions()
    events = session_service.get_recent_events()
    
    sessions_html = ""
    for s in sessions:
        sessions_html += f"""
        <tr>
            <td>{s.chat_id}</td>
            <td>{s.user_id or '-'}</td>
            <td class="time">{s.created_at.strftime('%Y-%m-%d %H:%M')}</td>
            <td><a href="/admin/session/{s.chat_id}" class="btn">View</a></td>
        </tr>
        """
    
    events_html = ""
    for e in events:
        events_html += f"""
        <tr>
            <td>{e.topic}</td>
            <td>{e.operation}</td>
            <td>{e.chat_id or '-'}</td>
            <td><span class="badge {e.processed}">{e.processed}</span></td>
            <td class="time">{e.created_at.strftime('%Y-%m-%d %H:%M:%S')}</td>
        </tr>
        """
    
    html_content = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>v7ai-fast - Admin</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; display: flex; justify-content: space-between; align-items: center; }}
        .header h1 {{ font-size: 24px; }}
        .nav a {{ color: white; margin-left: 20px; text-decoration: none; }}
        .container {{ max-width: 1200px; margin: 20px auto; padding: 0 20px; }}
        .card {{ background: white; border-radius: 12px; padding: 20px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); margin-bottom: 20px; }}
        .card h2 {{ color: #333; margin-bottom: 15px; padding-bottom: 10px; border-bottom: 1px solid #eee; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #eee; }}
        th {{ background: #f8f9fa; font-weight: 600; }}
        .badge {{ padding: 4px 12px; border-radius: 20px; font-size: 12px; font-weight: 500; }}
        .badge.success {{ background: #d4edda; color: #155724; }}
        .badge.failed {{ background: #f8d7da; color: #721c24; }}
        .btn {{ padding: 6px 12px; background: #667eea; color: white; border: none; border-radius: 6px; cursor: pointer; text-decoration: none; font-size: 14px; }}
        .btn:hover {{ background: #5a6fd6; }}
        .time {{ color: #888; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🤖 v7ai-fast Admin</h1>
        <div class="nav"><a href="/chat">Chat</a><a href="/admin">Admin</a></div>
    </div>
    <div class="container">
        <div class="card">
            <h2>📊 Recent Sessions</h2>
            <table>
                <thead><tr><th>Chat ID</th><th>User ID</th><th>Created At</th><th>Actions</th></tr></thead>
                <tbody>{sessions_html}</tbody>
            </table>
        </div>
        <div class="card">
            <h2>📝 Event Logs</h2>
            <table>
                <thead><tr><th>Topic</th><th>Operation</th><th>Chat ID</th><th>Status</th><th>Created At</th></tr></thead>
                <tbody>{events_html}</tbody>
            </table>
        </div>
    </div>
</body>
</html>
    """
    return HTMLResponse(content=html_content)


@router.get("/admin/session/{chat_id}", response_class=HTMLResponse)
async def session_detail(request: Request, chat_id: str, db: Session = Depends(get_db)):
    """Session detail page."""
    session_service = SessionService(db)
    messages = session_service.get_session_messages(chat_id)
    
    messages_html = ""
    for msg in messages:
        messages_html += f"""
        <div class="message {msg.role}-message">
            <div class="message-header">{msg.role.capitalize()}</div>
            <div>{msg.content}</div>
            <div class="time">{msg.created_at.strftime('%Y-%m-%d %H:%M:%S')}</div>
        </div>
        """
    
    if not messages_html:
        messages_html = '<p style="color: #888;">No messages found.</p>'
    
    html_content = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Session Detail - {chat_id}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; display: flex; justify-content: space-between; align-items: center; }}
        .header h1 {{ font-size: 24px; }}
        .nav a {{ color: white; margin-left: 20px; text-decoration: none; }}
        .container {{ max-width: 800px; margin: 20px auto; padding: 0 20px; }}
        .card {{ background: white; border-radius: 12px; padding: 20px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); }}
        .card h2 {{ color: #333; margin-bottom: 20px; padding-bottom: 10px; border-bottom: 1px solid #eee; }}
        .message {{ margin-bottom: 15px; padding: 12px 16px; border-radius: 12px; }}
        .user-message {{ background: #667eea; color: white; margin-left: 20%; }}
        .assistant-message {{ background: #f8f9fa; color: #333; margin-right: 20%; }}
        .message-header {{ font-size: 12px; opacity: 0.7; margin-bottom: 5px; }}
        .time {{ color: #888; font-size: 12px; text-align: right; margin-top: 5px; }}
        .btn {{ display: inline-block; padding: 8px 20px; background: #667eea; color: white; border: none; border-radius: 6px; cursor: pointer; text-decoration: none; font-size: 14px; margin-top: 20px; }}
        .btn:hover {{ background: #5a6fd6; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Session Detail: {chat_id}</h1>
        <div class="nav"><a href="/chat">Chat</a><a href="/admin">Admin</a></div>
    </div>
    <div class="container">
        <div class="card">
            <h2>📜 Messages</h2>
            {messages_html}
            <a href="/admin" class="btn">Back to Admin</a>
        </div>
    </div>
</body>
</html>
    """
    return HTMLResponse(content=html_content)


@router.get("/init-db")
async def init_database():
    """Initialize the database."""
    init_db()
    return {"message": "Database initialized successfully"}
