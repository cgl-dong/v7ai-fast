"""Web UI endpoints for chat and admin panel."""
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import datetime
import os

from app.core.database import get_db, init_db
from app.core.database import ChatMessage
from app.core.logging import logger
from app.services.session import SessionService
from app.services.deepseek import AIService
from app.services.auth import AuthService
from app.services.model_config import ModelConfigService

router = APIRouter()
templates = Jinja2Templates(directory="templates")
templates.env.cache_size = 0


def _get_ai_service(db: Session) -> AIService:
    """Create AIService using the active LLM config from database, falling back to .env."""
    service = ModelConfigService(db)
    active = service.get_active_config("llm")
    if active and active.api_key:
        return AIService(
            api_key=active.api_key,
            model=active.model_name,
            api_url=active.api_url
        )
    return AIService()
# Fix: Replace bytecode cache to avoid Windows Jinja2 dict key bug
templates.env.bytecode_cache = None

ADMIN_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>v7ai-fast - Admin</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f5f5;
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .header h1 {{ font-size: 24px; }}
        .nav a {{ color: white; margin-left: 20px; text-decoration: none; }}
        .container {{ max-width: 1400px; margin: 20px auto; padding: 0 20px; }}
        .card {{
            background: white;
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.05);
            margin-bottom: 20px;
        }}
        .card h2 {{
            color: #333;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 1px solid #eee;
        }}
        .card-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 1px solid #eee;
        }}
        .card-header h2 {{ margin: 0; padding: 0; border: none; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #eee; }}
        th {{ background: #f8f9fa; font-weight: 600; }}
        .badge {{
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 500;
        }}
        .badge.success {{ background: #d4edda; color: #155724; }}
        .badge.failed {{ background: #f8d7da; color: #721c24; }}
        .badge.active {{ background: #d1ecf1; color: #0c5460; }}
        .badge.type-llm {{ background: #fff3cd; color: #856404; }}
        .badge.type-embedding {{ background: #d4edda; color: #155724; }}
        .btn {{
            padding: 6px 12px;
            background: #667eea;
            color: white;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            text-decoration: none;
            font-size: 14px;
        }}
        .btn:hover {{ background: #5a6fd6; }}
        .btn-success {{ background: #28a745; }}
        .btn-success:hover {{ background: #218838; }}
        .btn-danger {{ background: #dc3545; }}
        .btn-danger:hover {{ background: #c82333; }}
        .btn-secondary {{ background: #6c757d; }}
        .btn-secondary:hover {{ background: #5a6268; }}
        .time {{ color: #888; font-size: 12px; }}
        .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
        .modal {{ display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); justify-content: center; align-items: center; z-index: 1000; }}
        .modal.active {{ display: flex; }}
        .modal-content {{ background: white; border-radius: 12px; padding: 25px; width: 90%; max-width: 500px; position: relative; }}
        .modal-content h3 {{ margin-bottom: 20px; color: #333; }}
        .modal-content .close {{ position: absolute; top: 15px; right: 15px; cursor: pointer; font-size: 20px; color: #999; }}
        .form-group {{ margin-bottom: 15px; }}
        .form-group label {{ display: block; margin-bottom: 5px; color: #555; font-weight: 500; }}
        .form-group input, .form-group select, .form-group textarea {{ width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 6px; font-size: 14px; }}
        .form-group textarea {{ resize: vertical; min-height: 80px; }}
        .form-row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }}
        .error-message {{ background: #f8d7da; color: #721c24; padding: 10px; border-radius: 6px; margin-bottom: 15px; display: none; }}
        .success-message {{ background: #d4edda; color: #155724; padding: 10px; border-radius: 6px; margin-bottom: 15px; display: none; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>v7ai-fast Admin</h1>
        <div class="nav">
            <a href="/chat">Chat</a>
            <a href="/admin">Admin</a>
        </div>
    </div>
    <div class="container">
        <div class="card">
            <div class="card-header">
                <h2>Model Configurations</h2>
                <button class="btn btn-success" onclick="openAddModelModal()">+ Add Model</button>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Type</th>
                        <th>Provider</th>
                        <th>Model</th>
                        <th>Status</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody id="model-table-body"></tbody>
            </table>
            <div id="no-models" style="text-align: center; color: #888; padding: 20px;">
                No models configured. Click "Add Model" to add one.
            </div>
        </div>

        <div class="card">
            <h2>Recent Sessions</h2>
            <table>
                <thead>
                    <tr>
                        <th>Chat ID</th>
                        <th>User ID</th>
                        <th>User Name</th>
                        <th>Created At</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {sessions_rows}
                </tbody>
            </table>
        </div>

        <div class="card">
            <h2>Event Logs</h2>
            <table>
                <thead>
                    <tr>
                        <th>Topic</th>
                        <th>Operation</th>
                        <th>Chat ID</th>
                        <th>User ID</th>
                        <th>Status</th>
                        <th>Created At</th>
                    </tr>
                </thead>
                <tbody>
                    {events_rows}
                </tbody>
            </table>
        </div>
    </div>

    <div id="model-modal" class="modal">
        <div class="modal-content">
            <span class="close" onclick="closeModelModal()">&times;</span>
            <h3 id="modal-title">Add Model Configuration</h3>
            <div class="error-message" id="modal-error"></div>
            <div class="success-message" id="modal-success"></div>
            <form id="model-form">
                <input type="hidden" id="model-id">
                <div class="form-row">
                    <div class="form-group">
                        <label>Model Type</label>
                        <select id="model-type" required>
                            <option value="llm">LLM Model</option>
                            <option value="embedding">Embedding Model</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Name</label>
                        <input type="text" id="model-name" required placeholder="e.g., DeepSeek Chat">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Provider</label>
                        <select id="model-provider" required>
                            <option value="deepseek">DeepSeek</option>
                            <option value="openai">OpenAI</option>
                            <option value="huggingface">HuggingFace</option>
                            <option value="custom">Custom</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Model Name</label>
                        <input type="text" id="model-model-name" placeholder="e.g., deepseek-chat">
                    </div>
                </div>
                <div class="form-group">
                    <label>API URL</label>
                    <input type="text" id="model-api-url" placeholder="e.g., https://api.deepseek.com/v1">
                </div>
                <div class="form-group">
                    <label>API Key</label>
                    <input type="password" id="model-api-key" placeholder="Enter API Key">
                </div>
                <div class="form-group">
                    <label>Description</label>
                    <textarea id="model-description" placeholder="Describe this configuration"></textarea>
                </div>
                <div class="form-group">
                    <label>
                        <input type="checkbox" id="model-is-active"> Set as Active
                    </label>
                </div>
                <div style="display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px;">
                    <button type="button" class="btn btn-secondary" onclick="closeModelModal()">Cancel</button>
                    <button type="submit" class="btn">Save</button>
                </div>
            </form>
        </div>
    </div>

    <script>
        let editingModelId = null;
        async function loadModels() {{
            try {{
                const response = await fetch('/api/v1/model/models');
                const models = await response.json();
                renderModels(models);
            }} catch (error) {{ console.error('Failed to load models:', error); }}
        }}
        function renderModels(models) {{
            const tbody = document.getElementById('model-table-body');
            const noModels = document.getElementById('no-models');
            if (models.length === 0) {{ tbody.innerHTML = ''; noModels.style.display = 'block'; return; }}
            noModels.style.display = 'none';
            tbody.innerHTML = models.map(model => `
                <tr>
                    <td>${{model.name}}</td>
                    <td><span class="badge type-${{model.model_type}}">${{model.model_type.toUpperCase()}}</span></td>
                    <td>${{model.provider}}</td>
                    <td>${{model.model_name || '-'}}</td>
                    <td>${{model.is_active ? '<span class="badge active">Active</span>' : '-'}}</td>
                    <td>
                        <button class="btn btn-secondary" style="padding: 4px 8px; font-size: 12px;" onclick="editModel(${{model.id}})">Edit</button>
                        <button class="btn btn-danger" style="padding: 4px 8px; font-size: 12px;" onclick="deleteModel(${{model.id}})">Delete</button>
                        ${{!model.is_active ? `<button class="btn btn-success" style="padding: 4px 8px; font-size: 12px;" onclick="activateModel(${{model.id}})">Activate</button>` : ''}}
                    </td>
                </tr>
            `).join('');
        }}
        function openAddModelModal() {{
            editingModelId = null;
            document.getElementById('modal-title').textContent = 'Add Model Configuration';
            document.getElementById('model-form').reset();
            document.getElementById('model-id').value = '';
            document.getElementById('modal-error').style.display = 'none';
            document.getElementById('modal-success').style.display = 'none';
            document.getElementById('model-modal').classList.add('active');
        }}
        function closeModelModal() {{ document.getElementById('model-modal').classList.remove('active'); }}
        async function editModel(id) {{
            try {{
                const response = await fetch(`/api/v1/model/models/${{id}}`);
                const model = await response.json();
                editingModelId = id;
                document.getElementById('modal-title').textContent = 'Edit Model Configuration';
                document.getElementById('model-id').value = model.id;
                document.getElementById('model-type').value = model.model_type;
                document.getElementById('model-name').value = model.name;
                document.getElementById('model-provider').value = model.provider;
                document.getElementById('model-model-name').value = model.model_name || '';
                document.getElementById('model-api-url').value = model.api_url || '';
                document.getElementById('model-api-key').value = model.api_key || '';
                document.getElementById('model-description').value = model.description || '';
                document.getElementById('model-is-active').checked = model.is_active;
                document.getElementById('modal-error').style.display = 'none';
                document.getElementById('modal-success').style.display = 'none';
                document.getElementById('model-modal').classList.add('active');
            }} catch (error) {{ console.error('Failed to load model:', error); }}
        }}
        async function deleteModel(id) {{
            if (!confirm('Are you sure you want to delete this model?')) return;
            try {{
                const response = await fetch(`/api/v1/model/models/${{id}}`, {{ method: 'DELETE' }});
                if (response.ok) {{ loadModels(); }}
            }} catch (error) {{ console.error('Failed to delete model:', error); }}
        }}
        async function activateModel(id) {{
            try {{
                const response = await fetch(`/api/v1/model/models/${{id}}/activate`, {{ method: 'POST' }});
                if (response.ok) {{ loadModels(); }}
            }} catch (error) {{ console.error('Failed to activate model:', error); }}
        }}
        document.getElementById('model-form').addEventListener('submit', async (e) => {{
            e.preventDefault();
            const data = {{
                model_type: document.getElementById('model-type').value,
                name: document.getElementById('model-name').value,
                provider: document.getElementById('model-provider').value,
                model_name: document.getElementById('model-model-name').value || undefined,
                api_url: document.getElementById('model-api-url').value || undefined,
                api_key: document.getElementById('model-api-key').value || undefined,
                description: document.getElementById('model-description').value || undefined,
                is_active: document.getElementById('model-is-active').checked
            }};
            try {{
                let response;
                if (editingModelId) {{
                    response = await fetch(`/api/v1/model/models/${{editingModelId}}`, {{
                        method: 'PUT', headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify(data)
                    }});
                }} else {{
                    response = await fetch('/api/v1/model/models', {{
                        method: 'POST', headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify(data)
                    }});
                }}
                if (response.ok) {{
                    document.getElementById('modal-success').textContent = editingModelId ? 'Updated successfully!' : 'Added successfully!';
                    document.getElementById('modal-success').style.display = 'block';
                    setTimeout(() => {{ closeModelModal(); loadModels(); }}, 1500);
                }} else {{
                    const error = await response.json();
                    document.getElementById('modal-error').textContent = error.detail || 'Operation failed';
                    document.getElementById('modal-error').style.display = 'block';
                }}
            }} catch (error) {{
                document.getElementById('modal-error').textContent = 'Network error, please retry';
                document.getElementById('modal-error').style.display = 'block';
            }}
        }});
        loadModels();
    </script>
</body>
</html>"""


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
    
    deepseek = _get_ai_service(db)
    try:
        answer = await deepseek.call_model(message)
    except RuntimeError as e:
        answer = str(e)
    except Exception as e:
        answer = f"AI调用异常: {e}"
    
    session_service.add_message(session.id, str(datetime.now().timestamp()), "assistant", answer)
    
    return {"response": answer, "session_id": session_id}


@router.get("/admin", response_class=HTMLResponse)
async def admin_panel(request: Request, db: Session = Depends(get_db)):
    """Admin panel page."""
    session_service = SessionService(db)
    sessions = session_service.get_sessions_with_user()
    events = session_service.get_recent_events()
    
    # Build sessions table rows
    sessions_rows = ""
    for s in sessions:
        sessions_rows += f"""
        <tr>
            <td>{s.chat_id}</td>
            <td>{s.user_id or '-'}</td>
            <td>{s.user_name or '-'}</td>
            <td class="time">{s.created_at.strftime('%Y-%m-%d %H:%M')}</td>
            <td><a href="/admin/session/{s.chat_id}" class="btn">View</a></td>
        </tr>"""
    
    # Build events table rows
    events_rows = ""
    for e in events:
        events_rows += f"""
        <tr>
            <td>{e.topic}</td>
            <td>{e.operation}</td>
            <td>{e.chat_id or '-'}</td>
            <td>{e.user_id or '-'}</td>
            <td><span class="badge {e.processed}">{e.processed}</span></td>
            <td class="time">{e.created_at.strftime('%Y-%m-%d %H:%M:%S')}</td>
        </tr>"""
    
    html = ADMIN_HTML_TEMPLATE.format(sessions_rows=sessions_rows, events_rows=events_rows)
    return HTMLResponse(content=html)


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


@router.get("/knowledge", response_class=HTMLResponse)
async def knowledge_page(request: Request):
    """Knowledge base management page."""
    return HTMLResponse(content=r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>知识库管理 - v7ai-fast</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f0f2f5; color: #333; min-height: 100vh; }
        .header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 16px 24px; display: flex; justify-content: space-between; align-items: center; }
        .header h1 { font-size: 20px; }
        .header nav a { color: white; text-decoration: none; margin-left: 20px; padding: 6px 14px; border-radius: 4px; background: rgba(255,255,255,0.2); }
        .header nav a:hover { background: rgba(255,255,255,0.35); }
        .container { max-width: 1100px; margin: 24px auto; padding: 0 16px; }
        .card { background: white; border-radius: 8px; padding: 24px; margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
        .card h2 { font-size: 18px; margin-bottom: 16px; }
        .upload-area { border: 2px dashed #d9d9d9; border-radius: 8px; padding: 40px; text-align: center; cursor: pointer; transition: border-color 0.3s, background 0.3s; }
        .upload-area:hover { border-color: #667eea; background: #f8f9ff; }
        .upload-area.dragover { border-color: #667eea; background: #eef0ff; }
        .upload-area p { color: #999; margin: 8px 0; }
        .upload-area .icon { font-size: 40px; margin-bottom: 8px; }
        #fileInput { display: none; }
        .upload-status { margin-top: 12px; padding: 8px 12px; border-radius: 4px; display: none; }
        .upload-status.success { display: block; background: #f6ffed; color: #52c41a; border: 1px solid #b7eb8f; }
        .upload-status.error { display: block; background: #fff2f0; color: #ff4d4f; border: 1px solid #ffccc7; }
        .stats-bar { display: flex; gap: 16px; margin-bottom: 20px; flex-wrap: wrap; }
        .stat-item { flex: 1; min-width: 120px; background: white; border-radius: 8px; padding: 16px; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
        .stat-item .num { font-size: 28px; font-weight: bold; color: #667eea; }
        .stat-item .label { font-size: 13px; color: #999; margin-top: 4px; }
        .toolbar { display: flex; gap: 8px; margin-bottom: 16px; align-items: center; }
        .btn { padding: 8px 16px; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; transition: opacity 0.2s; }
        .btn:hover { opacity: 0.85; }
        .btn-danger { background: #ff4d4f; color: white; }
        .btn-sm { padding: 4px 10px; font-size: 12px; }
        .btn-ghost { background: none; border: 1px solid #d9d9d9; color: #666; }
        .file-table { width: 100%; border-collapse: collapse; }
        .file-table th { text-align: left; padding: 10px 12px; background: #fafafa; border-bottom: 1px solid #f0f0f0; font-weight: 600; font-size: 13px; color: #666; }
        .file-table td { padding: 10px 12px; border-bottom: 1px solid #f0f0f0; font-size: 14px; }
        .file-table tr:hover { background: #f8f9ff; }
        .status-badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; }
        .status-uploaded { background: #e6f7ff; color: #1890ff; }
        .status-indexed { background: #f6ffed; color: #52c41a; }
        .status-error { background: #fff2f0; color: #ff4d4f; }
        .type-badge { display: inline-block; padding: 2px 8px; border-radius: 3px; font-size: 12px; background: #f5f5f5; color: #666; margin-right: 4px; }
        .empty-state { text-align: center; padding: 40px; color: #999; }
        .loading { text-align: center; padding: 20px; color: #999; }
    </style>
</head>
<body>
<div class="header">
    <h1>📚 知识库管理</h1>
    <nav>
        <a href="/chat">💬 聊天</a>
        <a href="/admin">⚙️ 控制面板</a>
        <a href="/login" onclick="logout()">登出</a>
    </nav>
</div>
<div class="container">
    <div class="stats-bar" id="statsBar">
        <div class="stat-item"><div class="num" id="statTotal">0</div><div class="label">总文件数</div></div>
        <div class="stat-item"><div class="num" id="statTxt">0</div><div class="label">TXT</div></div>
        <div class="stat-item"><div class="num" id="statPdf">0</div><div class="label">PDF</div></div>
        <div class="stat-item"><div class="num" id="statXlsx">0</div><div class="label">Excel</div></div>
        <div class="stat-item"><div class="num" id="statDocx">0</div><div class="label">Word</div></div>
        <div class="stat-item"><div class="num" id="statMd">0</div><div class="label">Markdown</div></div>
    </div>
    <div class="card">
        <h2>📤 上传文件</h2>
        <div class="upload-area" id="uploadArea" onclick="document.getElementById('fileInput').click()">
            <div class="icon">📁</div>
            <p>点击或拖拽文件到此处上传</p>
            <p style="font-size:12px;">支持 TXT / PDF / Excel / Word / Markdown / CSV</p>
        </div>
        <input type="file" id="fileInput" onchange="handleUpload(this.files[0])" accept=".txt,.pdf,.xlsx,.xls,.docx,.md,.csv">
        <div class="upload-status" id="uploadStatus"></div>
    </div>
    <div class="card">
        <div class="toolbar">
            <h2 style="flex:1;margin:0;">📋 文件列表</h2>
            <button class="btn btn-ghost" onclick="loadFiles()">🔄 刷新</button>
        </div>
        <div id="fileList"><div class="loading">加载中...</div></div>
    </div>
</div>
<script>
const API = "/api/v1/knowledge";
async function loadStats(){
    try{
        const r = await fetch(API+"/files/stats");
        const d = await r.json();
        document.getElementById("statTotal").textContent = d.total || 0;
        const bt = d.by_type || {};
        document.getElementById("statTxt").textContent = bt.txt || 0;
        document.getElementById("statPdf").textContent = bt.pdf || 0;
        document.getElementById("statXlsx").textContent = bt.xlsx || 0;
        document.getElementById("statDocx").textContent = bt.docx || 0;
        document.getElementById("statMd").textContent = bt.md || 0;
    }catch(e){console.error(e);}
}
async function loadFiles(){
    const el = document.getElementById("fileList");
    el.innerHTML='<div class="loading">加载中...</div>';
    try{
        const r = await fetch(API+"/files");
        const d = await r.json();
        if(!d.files||d.files.length===0){el.innerHTML='<div class="empty-state">暂无文件，请上传</div>';return;}
        let h = '<table class="file-table"><thead><tr><th>文件名</th><th>类型</th><th>大小</th><th>状态</th><th>分片</th><th>上传时间</th><th>操作</th></tr></thead><tbody>';
        d.files.forEach(function(f){
            var sz = f.file_size < 1024 ? f.file_size+'B' : f.file_size < 1048576 ? (f.file_size/1024).toFixed(1)+'KB' : (f.file_size/1048576).toFixed(1)+'MB';
            var ts = f.created_at ? f.created_at.slice(0,16).replace('T',' ') : '';
            var fn = he(f.filename);
            h += '<tr><td title="'+fn+'">'+he(f.filename.length>30?f.filename.slice(0,30)+'...':f.filename)+'</td><td><span class="type-badge">'+f.file_type.toUpperCase()+'</span></td><td>'+sz+'</td><td><span class="status-badge status-'+f.status+'">'+sl(f.status)+'</span>'+(f.error_msg?'<br><small style="color:#ff4d4f">'+he(f.error_msg.slice(0,40))+'</small>':'')+'</td><td>'+(f.chunk_count||0)+'</td><td>'+ts+'</td><td><button class="btn btn-ghost btn-sm" onclick="downloadFile('+f.id+',\''+fn+'\')">⬇下载</button> <button class="btn btn-danger btn-sm" onclick="deleteFile('+f.id+')">🗑删除</button></td></tr>';
        });
        h += '</tbody></table>';
        el.innerHTML = h;
    }catch(e){el.innerHTML='<div class="empty-state">加载失败: '+he(e.message)+'</div>';}
}
async function handleUpload(file){
    if(!file)return;
    var st = document.getElementById("uploadStatus");
    st.className="upload-status";st.textContent="上传中...";st.style.display="block";
    var fd = new FormData();fd.append("file",file);
    try{
        var r = await fetch(API+"/upload",{method:"POST",body:fd});
        var d = await r.json();
        if(r.ok){st.className="upload-status success";st.textContent=d.message+" - "+d.file.filename;loadFiles();loadStats();}
        else{st.className="upload-status error";st.textContent=d.detail||"上传失败";}
    }catch(e){st.className="upload-status error";st.textContent="上传失败: "+e.message;}
}
async function downloadFile(id,name){
    try{
        var r = await fetch(API+"/download/"+id);
        if(!r.ok){alert("下载失败");return;}
        var b = await r.blob();
        var u = URL.createObjectURL(b);
        var a = document.createElement("a");a.href=u;a.download=name;
        document.body.appendChild(a);a.click();document.body.removeChild(a);URL.revokeObjectURL(u);
    }catch(e){alert("下载失败: "+e.message);}
}
async function deleteFile(id){
    if(!confirm("确定要删除这个文件吗？"))return;
    try{
        var r = await fetch(API+"/files/"+id,{method:"DELETE"});
        if(r.ok){loadFiles();loadStats();}else{alert("删除失败");}
    }catch(e){alert("删除失败: "+e.message);}
}
function he(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
function sl(s){return {uploaded:'已上传',indexed:'已索引',error:'失败'}[s]||s;}
(function(){
    var ua = document.getElementById("uploadArea");
    ua.addEventListener("dragover",function(e){e.preventDefault();ua.classList.add("dragover");});
    ua.addEventListener("dragleave",function(){ua.classList.remove("dragover");});
    ua.addEventListener("drop",function(e){e.preventDefault();ua.classList.remove("dragover");handleUpload(e.dataTransfer.files[0]);});
})();
function logout(){document.cookie="access_token=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;";}
loadStats();loadFiles();
</script>
</body>
</html>""")


@router.get("/init-db")
async def init_database():
    """Initialize the database."""
    init_db()
    return {"message": "Database initialized successfully"}
