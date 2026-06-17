"""Web UI endpoints for chat and admin panel."""
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Optional
import os

from app.core.database import get_db, init_db, ChatMessage, ChatSession, User
from app.core.logging import logger
from app.core.settings import settings
from app.services.session import SessionService
from app.services.agent import RAGAgent
from app.services.auth import AuthService
from app.services.model_config import ModelConfigService
from app.api.v1.endpoints.auth import get_current_user

router = APIRouter()
templates = Jinja2Templates(directory="templates")
templates.env.cache_size = 0


async def get_optional_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    """Extract user from Authorization header or access_token cookie. Returns None if not logged in."""
    # Try Authorization header
    auth = request.headers.get("Authorization", "")
    token = None
    if auth.startswith("Bearer "):
        token = auth[7:]
    # Try cookie
    if not token:
        token = request.cookies.get("access_token", "")
    if not token:
        return None
    try:
        from jose import jwt
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        username = payload.get("sub")
        if username:
            return AuthService(db).get_user(username=username)
    except Exception:
        pass
    return None


def _get_agent(db: Session, session_id: str = "") -> RAGAgent:
    """Create RAGAgent with database session for retrieval + tracing."""
    return RAGAgent(db, session_id=session_id)

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
            <a href="/knowledge">Knowledge</a>
            <a href="/observability">Observability</a>
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


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Login page."""
    return HTMLResponse(content=r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>登录 - v7ai-fast</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);min-height:100vh;display:flex;align-items:center;justify-content:center}
        .card{background:#fff;border-radius:12px;padding:40px;width:380px;box-shadow:0 20px 60px rgba(0,0,0,.2)}
        .card h1{text-align:center;margin-bottom:24px;color:#333}
        .card input{width:100%;padding:12px 16px;margin-bottom:12px;border:1px solid #ddd;border-radius:8px;font-size:15px;outline:none}
        .card input:focus{border-color:#667eea}
        .card button{width:100%;padding:12px;background:#667eea;color:#fff;border:none;border-radius:8px;font-size:16px;cursor:pointer;margin-top:8px}
        .card button:hover{background:#5a6fd6}
        .error{color:#ff4d4f;font-size:13px;margin-bottom:8px;display:none}
        .link{text-align:center;margin-top:16px;font-size:13px}
        .link a{color:#667eea;text-decoration:none}
    </style>
</head>
<body>
<div class="card">
    <h1>v7ai-fast 登录</h1>
    <div class="error" id="error">用户名或密码错误</div>
    <input type="text" id="username" placeholder="用户名" autofocus>
    <input type="password" id="password" placeholder="密码">
    <button onclick="login()">登 录</button>
</div>
<script>
async function login(){
    var u=document.getElementById("username").value.trim();
    var p=document.getElementById("password").value.trim();
    if(!u||!p)return;
    var form=new FormData();form.append("username",u);form.append("password",p);
    try{
        var r=await fetch("/api/v1/auth/token",{method:"POST",body:form});
        if(!r.ok){document.getElementById("error").style.display="block";return}
        var d=await r.json();
        localStorage.setItem("token",d.access_token);
        localStorage.setItem("username",d.username);
        window.location.href="/chat";
    }catch(e){document.getElementById("error").style.display="block"}
}
document.getElementById("password").addEventListener("keypress",function(e){if(e.key==="Enter")login()});
</script>
</body>
</html>""")


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
async def get_sessions(
    request: Request,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_optional_user),
):
    """Get chat sessions for current user (or all if anonymous)."""
    if user:
        sessions = (
            db.query(ChatSession)
            .filter(ChatSession.user_id == str(user.id))
            .order_by(ChatSession.created_at.desc())
            .limit(50)
            .all()
        )
    else:
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
async def create_session(
    request: Request,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_optional_user),
):
    """Create a new empty chat session, bound to current user."""
    session_service = SessionService(db)
    username = user.username if user else "anonymous"
    user_id = str(user.id) if user else "anonymous"
    timestamp = str(datetime.now().timestamp())
    session_id = f"{username}-web-{timestamp}"
    session = session_service.get_or_create_session(session_id, user_id)
    if user:
        session.user_id = user_id
        session.user_name = username
        db.commit()
    return {"session_id": session.chat_id}


@router.post("/api/chat")
async def chat_message(
    request: Request,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_optional_user),
):
    """Handle chat message via LangGraph RAG Agent."""
    data = await request.json()
    message = data.get("message", "")
    username_prefix = (user.username if user else "anonymous") + "-web-"
    session_id = data.get("session_id", username_prefix + str(datetime.now().timestamp()))
    use_kb = data.get("use_kb", True)
    kb_id = data.get("kb_id")
    
    session_service = SessionService(db)
    user_id = str(user.id) if user else "anonymous"
    session = session_service.get_or_create_session(session_id, user_id)
    # Bind user info
    if user and not session.user_id:
        session.user_id = user_id
        session.user_name = user.username
        db.commit()
    session_service.add_message(session.id, str(datetime.now().timestamp()), "user", message)
    
    agent = _get_agent(db, session_id=session_id)
    answer = await agent.run(message, use_kb=use_kb, kb_id=kb_id)
    
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
            <div class="msg-content">{msg.content}</div>
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
        .msg-content p {{ margin: 4px 0; }}
        .msg-content ul, .msg-content ol {{ padding-left: 20px; }}
        .msg-content code {{ background: #f0f0f0; padding: 1px 4px; border-radius: 3px; }}
        .msg-content pre {{ background: #2d3748; color: #e2e8f0; padding: 10px; border-radius: 6px; overflow-x: auto; }}
    </style>
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
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
    <script>
        if (typeof marked !== 'undefined') {{
            marked.setOptions({{ breaks: true, gfm: true }});
            var elms = document.querySelectorAll('.assistant-message .msg-content');
            elms.forEach(function(el) {{
                el.innerHTML = marked.parse(el.textContent);
            }});
        }}
    </script>
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
        /* Preview modal */
        .modal-overlay{display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.45);z-index:1000;justify-content:center;align-items:center}
        .modal-overlay.show{display:flex}
        .modal{background:#fff;border-radius:8px;padding:24px;width:680px;max-width:95vw;max-height:85vh;overflow-y:auto}
        .modal h3{margin-bottom:12px;font-size:16px}
        .modal .preview-content{white-space:pre-wrap;font-family:Consolas,monospace;font-size:13px;line-height:1.6;background:#fafafa;padding:12px;border-radius:6px;max-height:60vh;overflow-y:auto}
        .modal .meta{font-size:12px;color:#999;margin-bottom:8px}
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
        <div class="toolbar">
            <h2 style="flex:1;margin:0;">📂 知识库分类</h2>
            <input type="text" id="kbNameInput" placeholder="新建知识库名称" style="padding:6px 10px;border:1px solid #ddd;border-radius:4px;font-size:13px;">
            <button class="btn btn-ghost" onclick="createKB()" style="background:#52c41a;color:#fff;border:none;">+ 创建</button>
        </div>
        <div id="kbList" style="display:flex;gap:8px;flex-wrap:wrap;"></div>
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
            <button class="btn btn-ghost" onclick="indexAllFiles()" style="background:#f6ad55;color:#fff;">🔍 索引全部</button>
            <button class="btn btn-ghost" onclick="loadFiles()">🔄 刷新</button>
        </div>
        <div id="fileList"><div class="loading">加载中...</div></div>
    </div>
</div>
<div class="modal-overlay" id="previewModal">
    <div class="modal">
        <h3>📄 文件预览</h3>
        <div class="meta" id="previewMeta"></div>
        <div class="preview-content" id="previewContent">加载中...</div>
        <div style="margin-top:12px;text-align:right;">
            <button class="btn btn-ghost btn-sm" onclick="document.getElementById('previewModal').classList.remove('show')" style="background:#f5f5f5;color:#666;">关闭</button>
        </div>
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
        let h = '<table class="file-table"><thead><tr><th>文件名</th><th>类型</th><th>大小</th><th>知识库</th><th>状态</th><th>分片</th><th>上传时间</th><th>操作</th></tr></thead><tbody>';
        d.files.forEach(function(f){
            var sz = f.file_size < 1024 ? f.file_size+'B' : f.file_size < 1048576 ? (f.file_size/1024).toFixed(1)+'KB' : (f.file_size/1048576).toFixed(1)+'MB';
            var ts = f.created_at ? f.created_at.slice(0,16).replace('T',' ') : '';
            var fn = he(f.filename);
            var kbTag = f.kb_name ? '<span style="background:#f0f2f5;padding:2px 8px;border-radius:4px;font-size:12px;cursor:pointer;" title="'+he(f.kb_name)+'">'+he(f.kb_name.slice(0,8))+'</span>' : '<span style="color:#ccc;font-size:12px;">未分类</span>';
            h += '<tr><td title="'+fn+'">'+he(f.filename.length>30?f.filename.slice(0,30)+'...':f.filename)+'</td><td><span class="type-badge">'+f.file_type.toUpperCase()+'</span></td><td>'+sz+'</td><td>'+kbTag+'</td><td><span class="status-badge status-'+f.status+'">'+sl(f.status)+'</span>'+(f.error_msg?'<br><small style="color:#ff4d4f">'+he(f.error_msg.slice(0,40))+'</small>':'')+'</td><td>'+(f.chunk_count||0)+'</td><td>'+ts+'</td><td><button class="btn btn-ghost btn-sm" onclick="previewFile('+f.id+',\''+fn+'\')" style="background:#1890ff;color:#fff;border:none;">👁 预览</button> <button class="btn btn-ghost btn-sm" onclick="indexFile('+f.id+')" style="background:#f6ad55;color:#fff;border:none;">🔍 索引</button> <select class="kb-select" onchange="moveFileToKb('+f.id+',this.value)" style="padding:2px 4px;font-size:11px;border-radius:4px;max-width:80px;"><option value="">移动至...</option><option value="">未分类</option>'+kbMoveOptions+'</select> <button class="btn btn-danger btn-sm" onclick="deleteFile('+f.id+')">🗑</button></td></tr>';
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
async function indexFile(id){
    var btn = event.target; btn.disabled=true; btn.textContent="索引中...";
    try{
        var r = await fetch(API+"/files/"+id+"/index",{method:"POST"});
        var d = await r.json();
        if(r.ok){alert("索引完成: "+d.chunks+" 个分片");loadFiles();loadStats();}
        else{alert("索引失败: "+(d.detail||"未知错误"));btn.disabled=false;btn.textContent="🔍 索引";}
    }catch(e){alert("索引失败: "+e.message);btn.disabled=false;btn.textContent="🔍 索引";}
}
async function indexAllFiles(){
    if(!confirm("将索引所有未索引的文件，可能需要几分钟。继续？"))return;
    var btn = event.target; btn.disabled=true; btn.textContent="索引中...";
    try{
        var r = await fetch(API+"/files/index-all",{method:"POST"});
        var d = await r.json();
        alert(d.message);
        loadFiles();loadStats();
    }catch(e){alert("批量索引失败: "+e.message);}
    btn.disabled=false; btn.textContent="🔍 索引全部";
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
async function previewFile(fileId,filename){
    var modal=document.getElementById("previewModal");
    var contentEl=document.getElementById("previewContent");
    var metaEl=document.getElementById("previewMeta");
    modal.classList.add("show");
    contentEl.textContent="加载中...";
    metaEl.textContent="";
    try{
        var r=await fetch(API+"/files/"+fileId+"/preview");
        if(!r.ok){contentEl.textContent="加载失败: "+r.status;return;}
        var d=await r.json();
        metaEl.textContent=he(d.filename)+" ("+d.file_type.toUpperCase()+", "+d.file_size+"B, "+d.content_length+"字"+(d.truncated?" 已截断":"")+")";
        contentEl.textContent=d.content||"(空文件)";
    }catch(e){contentEl.textContent="加载失败: "+e.message;}
}
(function(){
    var ua = document.getElementById("uploadArea");
    ua.addEventListener("dragover",function(e){e.preventDefault();ua.classList.add("dragover");});
    ua.addEventListener("dragleave",function(){ua.classList.remove("dragover");});
    ua.addEventListener("drop",function(e){e.preventDefault();ua.classList.remove("dragover");handleUpload(e.dataTransfer.files[0]);});
})();
function logout(){document.cookie="access_token=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;";}
var kbMoveOptions = "";
async function loadKBList(){
    try{
        var r=await fetch(API+"/kb/with-counts");var d=await r.json();
        var el=document.getElementById("kbList");el.innerHTML="";
        kbMoveOptions = "";
        d.knowledge_bases.forEach(function(k){
            var activeTag = k.is_active ? '<span style="color:#52c41a;font-size:11px;">● 启用</span>' : '<span style="color:#ccc;font-size:11px;">○ 已停用</span>';
            var toggleBtn = k.is_active ? '<button class="btn btn-sm" onclick="deactivateKB('+k.id+')" style="padding:2px 8px;font-size:11px;background:#faad14;color:#fff;border:none;">停用</button>' : '<button class="btn btn-sm" onclick="activateKB('+k.id+')" style="padding:2px 8px;font-size:11px;background:#52c41a;color:#fff;border:none;">启用</button>';
            var delBtn = '<button class="btn btn-sm" onclick="hardDeleteKB('+k.id+',\''+he(k.name)+'\')" style="padding:2px 8px;font-size:11px;background:#ff4d4f;color:#fff;border:none;">×</button>';
            el.innerHTML+='<div style="padding:6px 14px;background:#f0f2f5;border-radius:6px;display:flex;align-items:center;gap:8px;font-size:13px;"><span>'+he(k.name)+'</span>'+activeTag+'<span style="color:#999;font-size:11px;">('+(k.file_count||0)+'个文件)</span><span style="color:#999;font-size:11px;">'+(k.description||"")+'</span>'+toggleBtn+delBtn+'</div>';
            if (k.is_active) { kbMoveOptions += '<option value="'+k.id+'">'+he(k.name)+'</option>'; }
        });
    }catch(e){console.error(e)}
}
async function createKB(){
    var name=document.getElementById("kbNameInput").value.trim();
    if(!name){alert("请输入名称");return;}
    try{
        var r=await fetch(API+"/kb",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:name})});
        if(r.ok){document.getElementById("kbNameInput").value="";loadKBList();loadFiles();}
        else{alert("创建失败");}
    }catch(e){alert("创建失败: "+e.message)}
}
async function deactivateKB(id){
    if(!confirm("停用后该知识库不会显示在聊天选择中，已有文档绑定保留。继续？"))return;
    try{await fetch(API+"/kb/"+id,{method:"DELETE"});loadKBList();loadFiles();}
    catch(e){alert("操作失败: "+e.message)}
}
async function activateKB(id){
    try{await fetch(API+"/kb/"+id+"/activate",{method:"PUT"});loadKBList();loadFiles();}
    catch(e){alert("启用失败: "+e.message)}
}
async function hardDeleteKB(id,name){
    if(!confirm("彻底删除知识库【"+name+"】？关联文档将变为未分类。此操作不可恢复！"))return;
    try{await fetch(API+"/kb/"+id+"/hard",{method:"DELETE"});loadKBList();loadFiles();}
    catch(e){alert("删除失败: "+e.message)}
}
async function moveFileToKb(fileId,kbId){
    try{
        var r=await fetch(API+"/files/"+fileId+"/move",{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({kb_id:kbId})});
        if(r.ok)loadFiles();else alert("移动失败");
    }catch(e){alert("移动失败: "+e.message)}
}
loadKBList();
loadStats();loadFiles();
</script>
</body>
</html>""")


@router.get("/observability", response_class=HTMLResponse)
async def observability_page(request: Request):
    """Observability traces viewer + rating system."""
    return HTMLResponse(content=r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>可观测性 - v7ai-fast</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#f0f2f5;color:#333;min-height:100vh}
        .header{background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:#fff;padding:16px 24px;display:flex;justify-content:space-between;align-items:center}
        .header h1{font-size:20px}
        .header nav a{color:#fff;text-decoration:none;margin-left:20px;padding:6px 14px;border-radius:4px;background:rgba(255,255,255,.2)}
        .container{max-width:1300px;margin:24px auto;padding:0 16px}
        .card{background:#fff;border-radius:8px;padding:20px;margin-bottom:20px;box-shadow:0 1px 3px rgba(0,0,0,.1)}
        .card h2{font-size:18px;margin-bottom:16px}
        .stats-bar{display:flex;gap:16px;margin-bottom:20px;flex-wrap:wrap}
        .stat-item{flex:1;min-width:120px;background:#fff;border-radius:8px;padding:16px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.1)}
        .stat-item .num{font-size:28px;font-weight:bold;color:#667eea}
        .stat-item .label{font-size:13px;color:#999;margin-top:4px}
        table{width:100%;border-collapse:collapse;font-size:13px}
        th{text-align:left;padding:10px 8px;background:#fafafa;border-bottom:2px solid #f0f0f0;font-weight:600;color:#666}
        td{padding:8px;border-bottom:1px solid #f0f0f0}
        tr:hover{background:#f8f9ff}
        .badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px}
        .badge-success{background:#f6ffed;color:#52c41a}
        .badge-error{background:#fff2f0;color:#ff4d4f}
        .node-classify{color:#722ed1}
        .node-retrieve{color:#1890ff}
        .node-generate_with_docs,.node-generate_no_docs,.node-generate{color:#52c41a}
        .node-fallback{color:#fa8c16}
        .toolbar{display:flex;gap:8px;margin-bottom:12px;align-items:center}
        .btn{padding:6px 14px;border:none;border-radius:4px;cursor:pointer;font-size:13px;background:#667eea;color:#fff}
        .btn:hover{opacity:.85}
        .btn-sm{padding:3px 10px;font-size:11px;border:none;border-radius:3px;cursor:pointer}
        .btn-rate{background:#faad14;color:#fff}
        .btn-rate:hover{opacity:.85}
        .btn-star{background:none;border:none;cursor:pointer;font-size:16px;color:#faad14}
        .btn-star.empty{color:#ddd}
        select{padding:6px 10px;border:1px solid #d9d9d9;border-radius:4px;font-size:13px}
        .trace-id{font-family:monospace;font-size:12px;color:#999}
        .preview{max-width:250px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:inline-block}
        /* Modal */
        .modal-overlay{display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.45);z-index:1000;justify-content:center;align-items:center}
        .modal-overlay.show{display:flex}
        .modal{background:#fff;border-radius:8px;padding:24px;width:480px;max-width:95vw;max-height:85vh;overflow-y:auto}
        .modal h3{margin-bottom:16px;font-size:16px}
        .dim-group{margin-bottom:14px}
        .dim-group label{display:block;font-size:13px;color:#666;margin-bottom:4px}
        .dim-group .stars{display:flex;gap:4px}
        .form-row{display:flex;gap:8px;margin-top:16px}
        .form-row input,.form-row textarea{flex:1;padding:8px;border:1px solid #d9d9d9;border-radius:4px;font-size:13px}
        .form-row textarea{height:60px;resize:vertical}
        .btn-cancel{background:#f5f5f5;color:#666}
        .rating-score{display:inline-flex;align-items:center;gap:2px;font-size:12px}
        .rating-score .star{color:#faad14}
        .tabs{display:flex;gap:12px;margin-bottom:16px;border-bottom:2px solid #f0f0f0;padding-bottom:8px}
        .tab{cursor:pointer;padding:6px 16px;border-radius:4px 4px 0 0;font-size:14px;color:#666}
        .tab.active{color:#667eea;font-weight:600;border-bottom:2px solid #667eea;margin-bottom:-10px}
        .section{display:none}
        .section.active{display:block}
        .dim-bars{margin-top:12px}
        .dim-bar-row{display:flex;align-items:center;margin-bottom:6px;gap:8px}
        .dim-bar-row .dim-label{width:70px;font-size:12px;text-align:right;color:#666}
        .dim-bar-row .dim-bar{flex:1;height:14px;background:#f0f0f0;border-radius:7px;overflow:hidden}
        .dim-bar-row .dim-bar-fill{height:100%;border-radius:7px;background:linear-gradient(90deg,#faad14,#f5222d)}
        .dim-bar-row .dim-val{width:35px;font-size:12px;color:#333}
    </style>
</head>
<body>
<div class="header">
    <h1>📊 可观测性面板 (Observability)</h1>
    <nav>
        <a href="/chat">💬 聊天</a>
        <a href="/knowledge">📚 知识库</a>
        <a href="/admin">⚙️ 控制面板</a>
    </nav>
</div>
<div class="container">
    <div class="stats-bar" id="statsBar">
        <div class="stat-item"><div class="num" id="statTotal">0</div><div class="label">总追踪数</div></div>
        <div class="stat-item"><div class="num" id="statSuccess">0</div><div class="label">成功</div></div>
        <div class="stat-item"><div class="num" id="statError">0</div><div class="label">失败</div></div>
        <div class="stat-item"><div class="num" id="statAvgLatency">0ms</div><div class="label">平均延迟</div></div>
        <div class="stat-item"><div class="num" id="statAvgRating">-</div><div class="label">平均评分</div></div>
        <div class="stat-item"><div class="num" id="statRatingCount">0</div><div class="label">评分次数</div></div>
    </div>

    <div class="tabs">
        <div class="tab active" onclick="switchTab('traces')">🔍 调用追踪</div>
        <div class="tab" onclick="switchTab('ratings')">⭐ 评分管理</div>
    </div>

    <!-- Tab: Traces -->
    <div class="section active" id="sectionTraces">
        <div class="card">
            <div class="toolbar">
                <h2 style="flex:1;margin:0">📋 AI 调用链路追踪</h2>
                <select id="filterNode" onchange="loadTraces()">
                    <option value="">全部节点</option>
                    <option value="classify">classify</option>
                    <option value="retrieve">retrieve</option>
                    <option value="generate_with_docs">generate_with_docs</option>
                    <option value="generate_no_docs">generate_no_docs</option>
                    <option value="fallback">fallback</option>
                </select>
                <button class="btn" onclick="loadTraces()">🔄 刷新</button>
            </div>
            <div id="traceList">加载中...</div>
        </div>
    </div>

    <!-- Tab: Ratings -->
    <div class="section" id="sectionRatings">
        <div class="card">
            <div class="toolbar">
                <h2 style="flex:1;margin:0">⭐ 评分统计</h2>
                <select id="ratingFilterType" onchange="loadRatingStats()">
                    <option value="">全部类型</option>
                    <option value="trace">Trace(对话轮次)</option>
                    <option value="observation">Observation(观测步骤)</option>
                </select>
                <select id="ratingFilterNode" onchange="loadRatingStats()">
                    <option value="">全部节点</option>
                    <option value="classify">classify</option>
                    <option value="retrieve">retrieve</option>
                    <option value="generate_with_docs">generate_with_docs</option>
                    <option value="generate_no_docs">generate_no_docs</option>
                    <option value="fallback">fallback</option>
                </select>
                <select id="ratingFilterRater" onchange="loadRatingStats()">
                    <option value="">全部来源</option>
                    <option value="ai">AI 裁判</option>
                    <option value="human">人工评分</option>
                </select>
                <button class="btn" onclick="loadRatingStats();loadRatingList()">🔄 刷新</button>
            </div>
            <div id="ratingStats">加载中...</div>
            <div id="dimBars" class="dim-bars"></div>
        </div>
        <div class="card">
            <h2>📝 评分记录</h2>
            <div id="ratingList">请点击刷新加载</div>
        </div>
    </div>
</div>

<!-- Rating Modal -->
<div class="modal-overlay" id="ratingModal">
    <div class="modal">
        <h3>⭐ 质量评分</h3>
        <div id="ratingTargetInfo" style="font-size:12px;color:#999;margin-bottom:12px"></div>
        <div id="ratingDims"></div>
        <div class="form-row">
            <input type="text" id="ratingScorer" placeholder="评分人(可选)">
        </div>
        <div class="form-row">
            <textarea id="ratingComment" placeholder="评语/反馈(可选)"></textarea>
        </div>
        <div class="form-row">
            <button class="btn" onclick="submitRating()">✅ 提交评分</button>
            <button class="btn btn-cancel" onclick="closeRatingModal()">取消</button>
        </div>
    </div>
</div>

<script>
var API="/api/v1/observability";
var currentRatingTarget=null;
var currentRatingDims=[];

// ── Tab switching ────────────────────────────────────────────────
function switchTab(tab){
    document.querySelectorAll('.tab').forEach(function(t){t.classList.remove('active')});
    document.querySelectorAll('.section').forEach(function(s){s.classList.remove('active')});
    if(tab==='traces'){document.querySelector('.tab').classList.add('active');document.getElementById('sectionTraces').classList.add('active');loadTraces();loadStats()}
    else{document.querySelectorAll('.tab')[1].classList.add('active');document.getElementById('sectionRatings').classList.add('active');loadRatingStats();loadRatingList()}
}

// ── Trace stats ──────────────────────────────────────────────────
async function loadStats(){
    try{
        var r=await fetch(API+"/traces/stats");
        var d=await r.json();
        document.getElementById("statTotal").textContent=d.total||0;
        document.getElementById("statSuccess").textContent=d.success||0;
        document.getElementById("statError").textContent=d.error||0;
        document.getElementById("statAvgLatency").textContent=d.avg_latency_ms+"ms";
    }catch(e){console.error(e)}
}

async function loadTraces(){
    var el=document.getElementById("traceList");
    el.innerHTML="加载中...";
    var node=document.getElementById("filterNode").value;
    var url=API+"/traces?limit=50";
    if(node)url+="&node_name="+node;
    try{
        var r=await fetch(url);
        var d=await r.json();
        if(!d.traces||d.traces.length===0){el.innerHTML='<div style="text-align:center;padding:40px;color:#999">暂无追踪数据，尝试发送一条消息后再查看</div>';return}
        var h='<table><thead><tr><th>时间</th><th>Trace ID</th><th>节点</th><th>输入</th><th>输出</th><th>延迟</th><th>状态</th><th>AI评分</th><th>人工</th><th>操作</th></tr></thead><tbody>';
        d.traces.forEach(function(t){
            var time=t.created_at?t.created_at.slice(11,19):"";
            var nodeClass="node-"+t.node_name.replace("_with_docs","").replace("_no_docs","");
            var statusClass=t.status==="success"?"badge-success":"badge-error";
            var statusText=t.status==="success"?"成功":"失败";
            var latency=t.latency_ms+"ms";
            h+='<tr><td>'+time+'</td><td><span class="trace-id">'+t.trace_id+'</span></td><td class="'+nodeClass+'">'+t.node_name+'</td><td class="preview" title="'+he(t.input_summary||"")+'">'+he((t.input_summary||"").slice(0,25))+'</td><td class="preview" title="'+he(t.output_summary||"")+'">'+he((t.output_summary||"").slice(0,25))+'</td><td>'+latency+'</td><td><span class="badge '+statusClass+'">'+statusText+'</span>'+(t.error_msg?'<br><small style="color:#ff4d4f">'+he(t.error_msg.slice(0,20))+'</small>':'')+'</td><td id="score-ai-'+t.trace_id+'">-</td><td id="score-human-'+t.trace_id+'">-</td><td><button class="btn-sm btn-rate" onclick="openTraceRating(\''+t.trace_id+'\',\''+t.session_id+'\')">⭐ 评分</button></td></tr>';
        });
        h+='</tbody></table>';
        el.innerHTML=h;
        loadTraceRatings(d.traces);
    }catch(e){el.innerHTML='<div style="text-align:center;padding:40px;color:#ff4d4f">加载失败: '+e.message+'</div>'}
}

async function loadTraceRatings(traces){
    try{
        var r=await fetch(API+"/ratings?target_type=trace&limit=200");
        var d=await r.json();
        var aiScores={}, humanScores={};
        (d.ratings||[]).forEach(function(rt){
            var target=rt.target_id;
            if(rt.rater_type==="ai"){aiScores[target]=rt.overall_score}
            else{humanScores[target]=rt.overall_score}
        });
        traces.forEach(function(t){
            var aiEl=document.getElementById("score-ai-"+t.trace_id);
            var huEl=document.getElementById("score-human-"+t.trace_id);
            if(aiEl&&aiScores[t.trace_id]!==undefined){
                aiEl.innerHTML='<span style="font-size:11px;color:#8c6cef">🤖'+aiScores[t.trace_id]+'</span>';
            }
            if(huEl&&humanScores[t.trace_id]!==undefined){
                huEl.innerHTML='<span style="font-size:11px;color:#faad14">👤'+humanScores[t.trace_id]+'</span>';
            }
        });
    }catch(e){}
}

// ── Rating modal ─────────────────────────────────────────────────
function openTraceRating(traceId,sessionId){
    currentRatingTarget={type:"trace",id:traceId,session_id:sessionId,node_name:""};
    document.getElementById("ratingTargetInfo").innerHTML='<b>类型:</b> 对话轮次 (Trace) | <b>ID:</b> '+traceId;
    loadRatingDimensions("trace","");
    document.getElementById("ratingModal").classList.add("show");
}

async function loadRatingDimensions(targetType,nodeName){
    var url=API+"/ratings/dimensions?target_type="+targetType;
    if(nodeName)url+="&node_name="+nodeName;
    try{
        var r=await fetch(url);
        var d=await r.json();
        currentRatingDims=d.dimensions||[];
        renderDimStars(currentRatingDims);
    }catch(e){console.error(e)}
}

function renderDimStars(dims){
    var h='';
    dims.forEach(function(dim,i){
        h+='<div class="dim-group"><label>'+dim.label+' ('+dim.key+')</label><div class="stars">';
        for(var s=1;s<=dim.max;s++){
            h+='<button class="btn-star empty" id="star-'+i+'-'+s+'" onclick="setStar('+i+','+s+','+dim.max+')">★</button>';
        }
        h+='</div></div>';
    });
    document.getElementById("ratingDims").innerHTML=h||'<div style="color:#999;padding:12px">该类型暂无评分维度定义</div>';
}

function setStar(dimIdx,val,max){
    for(var s=1;s<=max;s++){
        var el=document.getElementById("star-"+dimIdx+"-"+s);
        if(el)el.classList.toggle("empty",s>val);
    }
    currentRatingDims[dimIdx].value=val;
}

function closeRatingModal(){
    document.getElementById("ratingModal").classList.remove("show");
    currentRatingTarget=null;
    currentRatingDims=[];
}

async function submitRating(){
    if(!currentRatingTarget)return;
    var dims={};
    currentRatingDims.forEach(function(d){
        if(d.value)dims[d.key]=d.value;
    });
    if(Object.keys(dims).length===0){alert("请至少对一个维度打分");return}

    var scorer=document.getElementById("ratingScorer").value||"anonymous";
    var comment=document.getElementById("ratingComment").value;
    try{
        var r=await fetch(API+"/ratings",{
            method:"POST",
            headers:{"Content-Type":"application/json"},
            body:JSON.stringify({
                target_type:currentRatingTarget.type,
                target_id:currentRatingTarget.id,
                session_id:currentRatingTarget.session_id,
                node_name:currentRatingTarget.node_name||"",
                scorer:scorer,
                rater_type:"human",
                dimension_scores:dims,
                comment:comment
            })
        });
        var d=await r.json();
        if(d.id){alert("评分已保存 (综合分: "+d.overall_score+")");closeRatingModal();loadTraces()}
    }catch(e){alert("提交失败: "+e.message)}
}

// ── Rating stats ─────────────────────────────────────────────────
async function loadRatingStats(){
    var el=document.getElementById("ratingStats");
    el.innerHTML="加载中...";
    var type=document.getElementById("ratingFilterType").value;
    var node=document.getElementById("ratingFilterNode").value;
    var rater=document.getElementById("ratingFilterRater").value;
    var url=API+"/ratings/stats?";
    if(type)url+="target_type="+type+"&";
    if(node)url+="node_name="+node+"&";
    if(rater)url+="rater_type="+rater+"&";
    try{
        var r=await fetch(url);
        var d=await r.json();
        if(!d.total){el.innerHTML='<div style="text-align:center;padding:20px;color:#999">暂无评分数据</div>';document.getElementById("statAvgRating").textContent="-";document.getElementById("statRatingCount").textContent="0";return}

        // Also load comparison
        var cmpUrl=API+"/ratings/compare?";
        if(node)cmpUrl+="node_name="+node;
        var cmpR=await fetch(cmpUrl);
        var cmp=await cmpR.json();

        document.getElementById("statAvgRating").textContent=d.avg_overall||"-";
        document.getElementById("statRatingCount").textContent=d.total||0;

        var h='<div style="display:flex;gap:16px"><div style="flex:1"><b>总评分数:</b> '+d.total+'</div><div style="flex:1"><b>平均分:</b> '+d.avg_overall+'/5</div></div>';

        // AI vs Human comparison
        h+='<div style="margin-top:12px;display:flex;gap:12px">';
        h+='<div style="flex:1;padding:10px;background:#f6f3ff;border-radius:6px"><b>🤖 AI 裁判</b><br><span style="font-size:13px">'+((cmp.ai||{}).avg_overall||"-")+'/5</span> <span style="font-size:11px;color:#999">('+((cmp.ai||{}).total||0)+'次)</span></div>';
        h+='<div style="flex:1;padding:10px;background:#fffbe6;border-radius:6px"><b>👤 人工评分</b><br><span style="font-size:13px">'+((cmp.human||{}).avg_overall||"-")+'/5</span> <span style="font-size:11px;color:#999">('+((cmp.human||{}).total||0)+'次)</span></div>';
        h+='</div>';

        // Per-node breakdown
        if(d.by_node&&Object.keys(d.by_node).length>0){
            h+='<div style="margin-top:12px"><b>按节点:</b> ';
            var nodes=[];
            for(var n in d.by_node){nodes.push(n+': '+d.by_node[n].avg_overall+' ('+d.by_node[n].count+'次)')}
            h+=nodes.join(' | ')+'</div>';
        }
        el.innerHTML=h;

        // Dimension bars
        var barHtml='';
        if(d.by_dimension&&Object.keys(d.by_dimension).length>0){
            for(var k in d.by_dimension){
                var v=d.by_dimension[k];
                var pct=(v.avg/5*100);
                barHtml+='<div class="dim-bar-row"><span class="dim-label">'+v.label+'</span><div class="dim-bar"><div class="dim-bar-fill" style="width:'+pct+'%"></div></div><span class="dim-val">'+v.avg+'</span></div>';
            }
        }
        document.getElementById("dimBars").innerHTML=barHtml;
    }catch(e){el.innerHTML='<div style="color:#ff4d4f">加载失败: '+e.message+'</div>'}
}

async function loadRatingList(){
    var el=document.getElementById("ratingList");
    el.innerHTML="加载中...";
    try{
        var r=await fetch(API+"/ratings?limit=30");
        var d=await r.json();
        if(!d.ratings||d.ratings.length===0){el.innerHTML='<div style="text-align:center;padding:20px;color:#999">暂无评分记录</div>';return}
        var h='<table><thead><tr><th>时间</th><th>来源</th><th>类型</th><th>目标ID</th><th>节点</th><th>评分人/模型</th><th>维度评分</th><th>综合</th><th>评语</th></tr></thead><tbody>';
        d.ratings.forEach(function(rt){
            var time=rt.created_at?rt.created_at.slice(0,16):"";
            var srcTag=rt.rater_type==="ai"?'<span style="color:#8c6cef;font-size:11px">🤖 AI</span>':'<span style="color:#faad14;font-size:11px">👤 人工</span>';
            var scorerLabel=rt.rater_type==="ai"?(rt.judge_model||rt.scorer):rt.scorer;
            var dimsHtml='';
            var ds=rt.dimension_scores||{};
            var rs=rt.dimension_reasons||{};
            for(var k in ds){
                var reason=rs[k]?' title="'+he(rs[k])+'"':'';
                dimsHtml+='<span style="margin-right:4px;font-size:11px"'+reason+'>'+k+':'+ds[k]+'</span>'
            }
            var stars='';
            for(var i=0;i<Math.round(rt.overall_score);i++)stars+='<span class="star">★</span>';
            h+='<tr><td>'+time+'</td><td>'+srcTag+'</td><td>'+rt.target_type+'</td><td style="font-family:monospace;font-size:11px">'+rt.target_id.slice(0,12)+'</td><td>'+rt.node_name+'</td><td style="font-size:11px">'+he(scorerLabel)+'</td><td>'+dimsHtml+'</td><td><span class="rating-score">'+stars+' '+rt.overall_score+'</span></td><td style="max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+he(rt.comment||"")+'</td></tr>';
        });
        h+='</tbody></table>';
        el.innerHTML=h;
    }catch(e){el.innerHTML='<div style="color:#ff4d4f">加载失败: '+e.message+'</div>'}
}

function he(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}

// Init
loadStats();loadTraces();
</script>
</body>
</html>""")


@router.get("/init-db")
async def init_database():
    """Initialize the database."""
    init_db()
    return {"message": "Database initialized successfully"}
