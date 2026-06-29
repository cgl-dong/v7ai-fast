"""知识库文件上传/下载/索引 API — with user isolation"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from app.core.database import get_db, User, KnowledgeBase, KnowledgeFile
from app.core.logging import logger
from app.services.knowledge import KnowledgeService
from app.services.indexer import Indexer
from app.services.kb_service import KnowledgeBaseService
from app.services.chunking import list_strategies as get_available_strategies
from app.api.v1.endpoints.auth import get_current_user
from app.services.auth import AuthService
from app.core.settings import settings
from minio.error import S3Error
from urllib.parse import quote
import io
from typing import Optional

router = APIRouter()


async def get_optional_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    """Extract user from Authorization header or access_token cookie. Returns None if not logged in."""
    auth = request.headers.get("Authorization", "")
    token = None
    if auth.startswith("Bearer "):
        token = auth[7:]
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


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5
    kb_id: Optional[int] = None
    metadata_filter: Optional[dict] = Field(None, description="元数据过滤: {\"file_type\":\"pdf\", \"filename\":\"%报告%\", \"date_from\":\"2025-01-01\", \"metadata.chunk_strategy\":\"section\"}")


class IndexRequest(BaseModel):
    """索引参数：覆盖该文件的默认分片策略"""
    strategy: Optional[str] = Field(None, description="切分策略: recursive/sentence/section/qa/semantic/token/paragraph/fixed/excel")
    chunk_size: Optional[int] = Field(None, ge=64, le=8192, description="每片字符数")
    chunk_overlap: Optional[int] = Field(None, ge=0, le=2048, description="重叠字符数")
    skills: Optional[list[str]] = Field(None, description="技能管线: 例如 ['pdf_to_docx']，按顺序执行")


def _to_file_info(f, kb_map: dict = None) -> dict:
    info = {
        "id": f.id,
        "kb_id": getattr(f, 'kb_id', None),
        "kb_name": kb_map.get(f.kb_id) if kb_map and f.kb_id else None,
        "filename": f.filename,
        "file_type": f.file_type,
        "file_size": f.file_size,
        "status": f.status,
        "chunk_count": f.chunk_count,
        "chunk_strategy": getattr(f, 'chunk_strategy', None),
        "chunk_size": getattr(f, 'chunk_size', None),
        "chunk_overlap": getattr(f, 'chunk_overlap', None),
        "error_msg": f.error_msg,
        "uploader": f.uploader or "anonymous",
        "created_at": f.created_at.isoformat() if f.created_at else ""
    }
    return info


# ── 可用策略列表 ────────────────────────────────────────────────

@router.get("/chunk-strategies")
async def list_chunk_strategies():
    """返回所有可用的分片策略及说明"""
    return {
        "strategies": get_available_strategies(),
        "defaults_per_file_type": {k: {
            "strategy": v.strategy,
            "chunk_size": v.chunk_size,
            "chunk_overlap": v.chunk_overlap,
        } for k, v in __import__("app.services.chunking", fromlist=["CHUNK_CONFIG"]).CHUNK_CONFIG.items()}
    }


# ── 文件 CRUD ───────────────────────────────────────────────────

@router.get("/files")
async def list_files(
    file_type: str = Query(None),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    svc = KnowledgeService(db)
    user_id = current_user.id if current_user else None
    files = svc.get_all_files(file_type=file_type, user_id=user_id)
    kb_map = _load_kb_map(db, user_id=user_id)
    return {"files": [_to_file_info(f, kb_map) for f in files], "total": len(files)}


@router.get("/files/stats")
async def file_stats(
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    svc = KnowledgeService(db)
    user_id = current_user.id if current_user else None
    return svc.get_file_stats(user_id=user_id)


@router.get("/files/{file_id}")
async def get_file_info(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    svc = KnowledgeService(db)
    user_id = current_user.id if current_user else None
    f = svc.get_file_by_id(file_id, user_id=user_id)
    if not f:
        raise HTTPException(status_code=404, detail="文件不存在")
    return _to_file_info(f)


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    strategy: Optional[str] = Query(None, description="切分策略，不传则按文件类型自动选择"),
    chunk_size: Optional[int] = Query(None, ge=64, le=8192, description="每片字符数"),
    chunk_overlap: Optional[int] = Query(None, ge=0, le=2048, description="重叠字符数"),
    skills: Optional[str] = Query(None, description="技能管线，逗号分隔，例如 'pdf_to_docx'"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """上传文件，可选指定分片策略和技能管线。

    策略参数会保存到文件记录中，后续索引时自动使用。
    如果不传，索引时按文件类型走默认配置。

    技能管线会在索引时对文件内容进行转换（如 PDF→DOCX），
    原始文件不受影响。
    """
    svc = KnowledgeService(db)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")
    try:
        record = svc.save_upload(
            content, file.filename or "unknown",
            uploader=current_user.username,
            chunk_strategy=strategy,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            user_id=current_user.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except S3Error as e:
        logger.error(f"MinIO upload error: {e}")
        raise HTTPException(status_code=503, detail=f"MinIO 存储服务异常: {e.message}")
    except Exception as e:
        logger.error(f"Upload error: {e}")
        raise HTTPException(status_code=503, detail=f"上传失败: {str(e)}")

    # Parse skills if provided (comma-separated string)
    skill_list = [s.strip() for s in skills.split(",") if s.strip()] if skills else None
    if skill_list:
        logger.info(f"Upload with skills hint: {skill_list} (apply at index time)")

    return {
        "message": "上传成功",
        "file": _to_file_info(record),
        "skills_hint": skill_list,
    }


@router.get("/download/{file_id}")
async def download_file(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    svc = KnowledgeService(db)
    user_id = current_user.id if current_user else None
    try:
        content, filename, content_type = svc.get_file_content(file_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return StreamingResponse(
        io.BytesIO(content),
        media_type=content_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"}
    )


@router.get("/files/{file_id}/preview")
async def preview_file(
    file_id: int,
    max_chars: int = Query(10000, ge=1000, le=50000),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    """预览文件解析后的文本内容"""
    svc = KnowledgeService(db)
    user_id = current_user.id if current_user else None
    record = svc.get_file_by_id(file_id, user_id=user_id)
    if not record:
        raise HTTPException(status_code=404, detail="文件不存在")
    try:
        content_bytes, _, _ = svc.get_file_content(file_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Parse with same logic as indexer
    from app.services.indexer import Indexer
    idx = Indexer(db)
    text = idx._parse_content(content_bytes, record.filename, record.file_type)

    truncated = len(text) > max_chars
    text = text[:max_chars]
    return {
        "file_id": file_id,
        "filename": record.filename,
        "file_type": record.file_type,
        "file_size": record.file_size,
        "content": text,
        "content_length": len(text),
        "truncated": truncated,
    }


@router.delete("/files/{file_id}")
async def delete_file(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = KnowledgeService(db)
    # Verify ownership
    f = svc.get_file_by_id(file_id, user_id=current_user.id)
    if not f:
        raise HTTPException(status_code=404, detail="文件不存在或无权限")
    success = svc.delete_file(file_id)
    if not success:
        raise HTTPException(status_code=404, detail="文件不存在")
    return {"message": "删除成功"}


# ── 索引操作 ────────────────────────────────────────────────────

def _run_index_task(file_id: int, strategy: str = None, chunk_size: int = None,
                    chunk_overlap: int = None, skills: list[str] = None):
    """Background index task with its own DB session."""
    import logging
    logger_bg = logging.getLogger("v7ai-fast.knowledge")
    from app.core.database import SessionLocal
    db = SessionLocal()
    try:
        indexer = Indexer(db)
        result = indexer.index_file(file_id, strategy=strategy, chunk_size=chunk_size,
                                    chunk_overlap=chunk_overlap, skills=skills)
        logger_bg.info(f"[bg-index] file={file_id} done: {result}")
    except Exception as e:
        logger_bg.error(f"[bg-index] file={file_id} failed: {e}")
    finally:
        db.close()


@router.post("/files/{file_id}/index")
async def index_file(
    file_id: int,
    params: Optional[IndexRequest] = None,
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """异步索引：立即返回，后台执行分片+Embedding+存储。

    请求体可选覆盖切分策略参数：
    ```json
    {"strategy": "section", "chunk_size": 1024, "chunk_overlap": 128}
    ```
    """
    record = db.query(KnowledgeFile).filter(KnowledgeFile.id == file_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="文件不存在")
    # Verify ownership
    from sqlalchemy import or_
    if record.user_id is not None and record.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权限操作此文件")

    strategy = params.strategy if (params and params.strategy) else getattr(record, 'chunk_strategy', None)
    chunk_size = params.chunk_size if (params and params.chunk_size) else getattr(record, 'chunk_size', None)
    chunk_overlap = params.chunk_overlap if (params and params.chunk_overlap) else getattr(record, 'chunk_overlap', None)
    skills = params.skills if (params and params.skills) else None

    background_tasks.add_task(_run_index_task, file_id, strategy=strategy, chunk_size=chunk_size,
                              chunk_overlap=chunk_overlap, skills=skills)
    logger.info(f"Index task queued for file={file_id}" + (f" with skills={skills}" if skills else ""))
    return {"message": "索引任务已提交，正在后台处理", "file_id": file_id}


@router.post("/files/index-all")
async def index_all_files(
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = None,
    current_user: User = Depends(get_current_user),
):
    """批量异步索引所有未索引的文件（使用各文件上传时指定的策略或默认策略）"""
    from sqlalchemy import or_
    files = db.query(KnowledgeFile).filter(
        KnowledgeFile.status != "indexed",
        or_(KnowledgeFile.user_id == current_user.id, KnowledgeFile.user_id.is_(None)),
    ).all()
    if not files:
        return {"message": "所有文件已索引", "count": 0}

    for f in files:
        background_tasks.add_task(
            _run_index_task, f.id,
            strategy=getattr(f, 'chunk_strategy', None),
            chunk_size=getattr(f, 'chunk_size', None),
            chunk_overlap=getattr(f, 'chunk_overlap', None),
        )

    logger.info(f"Batch index queued: {len(files)} files")
    return {"message": f"已提交 {len(files)} 个文件的索引任务，正在后台处理", "count": len(files)}


# ── 语义搜索 ────────────────────────────────────────────────────

@router.post("/search")
async def search_knowledge(
    req: SearchRequest,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    """语义搜索知识库（支持知识库筛选 + 元数据过滤）"""
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="查询内容不能为空")
    indexer = Indexer(db)
    try:
        user_id = current_user.id if current_user else None
        results = indexer.search_chunks(
            req.query, req.top_k, req.kb_id,
            user_id=user_id,
            metadata_filter=req.metadata_filter,
        )
    except Exception as e:
        logger.error(f"Search error: {e}")
        raise HTTPException(status_code=500, detail=f"搜索失败: {str(e)}")
    return {"query": req.query, "results": results, "count": len(results)}


# ── 知识库分类管理 ─────────────────────────────────────────────

class KBCreate(BaseModel):
    name: str
    description: str = ""


class KBUpdate(BaseModel):
    name: str = None
    description: str = None
    is_active: bool = None


class FileMoveRequest(BaseModel):
    kb_id: int = None  # None = remove from KB


class BatchMoveRequest(BaseModel):
    file_ids: list[int]
    kb_id: int = None  # None = remove from KB


# ── Helper ───────────────────────────────────────────────────────

def _load_kb_map(db: Session, user_id: Optional[int] = None) -> dict:
    """Load all knowledge bases into {id: name} dict for efficient lookups."""
    q = db.query(KnowledgeBase)
    if user_id is not None:
        from sqlalchemy import or_
        q = q.filter(or_(KnowledgeBase.user_id == user_id, KnowledgeBase.user_id.is_(None)))
    kbs = q.all()
    return {k.id: k.name for k in kbs}


@router.get("/kb")
async def list_knowledge_bases(
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    """列出所有活跃的知识库分类（聊天用）"""
    svc = KnowledgeBaseService(db)
    user_id = current_user.id if current_user else None
    kbs = svc.get_active(user_id=user_id)  # Only active KBs
    return {"knowledge_bases": [{"id": k.id, "name": k.name, "description": k.description,
            "is_active": k.is_active, "user_id": k.user_id,
            "created_at": k.created_at.isoformat() if k.created_at else ""} for k in kbs]}


@router.post("/kb")
async def create_knowledge_base(
    data: KBCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建知识库分类"""
    svc = KnowledgeBaseService(db)
    try:
        kb = svc.create(data.name, data.description, user_id=current_user.id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"创建失败: {e}")
    return {"id": kb.id, "name": kb.name, "message": "创建成功"}


@router.put("/kb/{kb_id}")
async def update_knowledge_base(
    kb_id: int,
    data: KBUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = KnowledgeBaseService(db)
    kb = svc.update(kb_id, data.model_dump(exclude_none=True), user_id=current_user.id)
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在或无权限")
    return {"id": kb.id, "message": "更新成功"}


@router.delete("/kb/{kb_id}")
async def deactivate_knowledge_base(
    kb_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """停用知识库（软删除，文档绑定保留）"""
    svc = KnowledgeBaseService(db)
    if not svc.deactivate(kb_id, user_id=current_user.id):
        raise HTTPException(status_code=404, detail="知识库不存在或无权限")
    return {"message": "知识库已停用"}


@router.put("/kb/{kb_id}/activate")
async def activate_knowledge_base(
    kb_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """重新启用知识库"""
    svc = KnowledgeBaseService(db)
    if not svc.activate(kb_id, user_id=current_user.id):
        raise HTTPException(status_code=404, detail="知识库不存在或无权限")
    return {"message": "知识库已启用"}


@router.delete("/kb/{kb_id}/hard")
async def hard_delete_knowledge_base(
    kb_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """物理删除知识库（清除关联文档的绑定）"""
    svc = KnowledgeBaseService(db)
    if not svc.hard_delete(kb_id, user_id=current_user.id):
        raise HTTPException(status_code=404, detail="知识库不存在或无权限")
    return {"message": "知识库已彻底删除"}


@router.get("/kb/with-counts")
async def list_kb_with_counts(
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    """列出知识库并附带文档数量"""
    svc = KnowledgeBaseService(db)
    user_id = current_user.id if current_user else None
    return {"knowledge_bases": svc.get_with_file_counts(user_id=user_id)}


@router.put("/files/{file_id}/move")
async def move_file_to_kb(
    file_id: int,
    data: FileMoveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """将文件移动到指定知识库"""
    f = db.query(KnowledgeFile).filter(KnowledgeFile.id == file_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="文件不存在")
    # Verify ownership: only allow moving own files or shared files
    if f.user_id is not None and f.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权限操作此文件")
    f.kb_id = data.kb_id
    db.commit()
    kb_name = "通用"
    if data.kb_id:
        kb = KnowledgeBaseService(db).get_by_id(data.kb_id, user_id=current_user.id)
        kb_name = kb.name if kb else str(data.kb_id)
    return {"message": f"已移至: {kb_name}", "kb_id": data.kb_id}


@router.post("/files/move-batch")
async def batch_move_files(
    data: BatchMoveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """批量移动文件到指定知识库"""
    from sqlalchemy import or_
    updated = db.query(KnowledgeFile).filter(
        KnowledgeFile.id.in_(data.file_ids),
        or_(KnowledgeFile.user_id == current_user.id, KnowledgeFile.user_id.is_(None)),
    ).update(
        {"kb_id": data.kb_id}, synchronize_session=False
    )
    db.commit()
    kb_name = "通用"
    if data.kb_id:
        kb = KnowledgeBaseService(db).get_by_id(data.kb_id, user_id=current_user.id)
        kb_name = kb.name if kb else str(data.kb_id)
    logger.info(f"Batch moved {updated} files to KB: {kb_name} (id={data.kb_id}) by user={current_user.username}")
    return {"message": f"已将 {updated} 个文件移至: {kb_name}", "count": updated, "kb_id": data.kb_id}
