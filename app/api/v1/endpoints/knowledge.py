"""知识库文件上传/下载/索引 API"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from app.core.database import get_db
from app.core.logging import logger
from app.services.knowledge import KnowledgeService
from app.services.indexer import Indexer
from app.services.kb_service import KnowledgeBaseService
from app.services.chunking import list_strategies as get_available_strategies
from minio.error import S3Error
from urllib.parse import quote
import io
from typing import Optional

router = APIRouter()


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5
    kb_id: Optional[int] = None


class IndexRequest(BaseModel):
    """索引参数：覆盖该文件的默认分片策略"""
    strategy: Optional[str] = Field(None, description="切分策略: recursive/sentence/section/qa/semantic/token/paragraph/fixed/excel")
    chunk_size: Optional[int] = Field(None, ge=64, le=8192, description="每片字符数")
    chunk_overlap: Optional[int] = Field(None, ge=0, le=2048, description="重叠字符数")


def _to_file_info(f) -> dict:
    return {
        "id": f.id,
        "kb_id": getattr(f, 'kb_id', None),
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
async def list_files(file_type: str = Query(None), db: Session = Depends(get_db)):
    svc = KnowledgeService(db)
    files = svc.get_all_files(file_type=file_type)
    return {"files": [_to_file_info(f) for f in files], "total": len(files)}


@router.get("/files/stats")
async def file_stats(db: Session = Depends(get_db)):
    svc = KnowledgeService(db)
    return svc.get_file_stats()


@router.get("/files/{file_id}")
async def get_file_info(file_id: int, db: Session = Depends(get_db)):
    svc = KnowledgeService(db)
    f = svc.get_file_by_id(file_id)
    if not f:
        raise HTTPException(status_code=404, detail="文件不存在")
    return _to_file_info(f)


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    strategy: Optional[str] = Query(None, description="切分策略，不传则按文件类型自动选择"),
    chunk_size: Optional[int] = Query(None, ge=64, le=8192, description="每片字符数"),
    chunk_overlap: Optional[int] = Query(None, ge=0, le=2048, description="重叠字符数"),
    db: Session = Depends(get_db),
):
    """上传文件，可选指定分片策略。

    策略参数会保存到文件记录中，后续索引时自动使用。
    如果不传，索引时按文件类型走默认配置。
    """
    svc = KnowledgeService(db)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")
    try:
        record = svc.save_upload(
            content, file.filename or "unknown",
            chunk_strategy=strategy,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except S3Error as e:
        logger.error(f"MinIO upload error: {e}")
        raise HTTPException(status_code=503, detail=f"MinIO 存储服务异常: {e.message}")
    except Exception as e:
        logger.error(f"Upload error: {e}")
        raise HTTPException(status_code=503, detail=f"上传失败: {str(e)}")
    return {"message": "上传成功", "file": _to_file_info(record)}


@router.get("/download/{file_id}")
async def download_file(file_id: int, db: Session = Depends(get_db)):
    svc = KnowledgeService(db)
    try:
        content, filename, content_type = svc.get_file_content(file_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return StreamingResponse(
        io.BytesIO(content),
        media_type=content_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"}
    )


@router.delete("/files/{file_id}")
async def delete_file(file_id: int, db: Session = Depends(get_db)):
    svc = KnowledgeService(db)
    success = svc.delete_file(file_id)
    if not success:
        raise HTTPException(status_code=404, detail="文件不存在")
    return {"message": "删除成功"}


# ── 索引操作 ────────────────────────────────────────────────────

@router.post("/files/{file_id}/index")
async def index_file(file_id: int, params: Optional[IndexRequest] = None, db: Session = Depends(get_db)):
    """对文件进行向量索引（分片→Embedding→存储到pgvector）。

    请求体可选覆盖切分策略参数：
    ```json
    {"strategy": "section", "chunk_size": 1024, "chunk_overlap": 128}
    ```
    如果不传，使用上传时保存的策略；如果上传时也没指定，按文件类型走默认。
    """
    indexer = Indexer(db)

    # 如果有策略参数，优先使用显式传入的；否则看文件记录上存的是什么
    record = db.query(__import__("app.core.database", fromlist=["KnowledgeFile"]).KnowledgeFile).filter(
        __import__("app.core.database", fromlist=["KnowledgeFile"]).KnowledgeFile.id == file_id
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="文件不存在")

    strategy = params.strategy if (params and params.strategy) else getattr(record, 'chunk_strategy', None)
    chunk_size = params.chunk_size if (params and params.chunk_size) else getattr(record, 'chunk_size', None)
    chunk_overlap = params.chunk_overlap if (params and params.chunk_overlap) else getattr(record, 'chunk_overlap', None)

    try:
        result = indexer.index_file(file_id, strategy=strategy, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"索引失败: {str(e)}")
    return result


@router.post("/files/index-all")
async def index_all_files(db: Session = Depends(get_db)):
    """批量索引所有未索引的文件（使用各文件上传时指定的策略或默认策略）"""
    from app.core.database import KnowledgeFile
    files = db.query(KnowledgeFile).filter(KnowledgeFile.status != "indexed").all()
    if not files:
        return {"message": "所有文件已索引", "count": 0}

    indexer = Indexer(db)
    results = []
    for f in files:
        try:
            r = indexer.index_file(
                f.id,
                strategy=getattr(f, 'chunk_strategy', None),
                chunk_size=getattr(f, 'chunk_size', None),
                chunk_overlap=getattr(f, 'chunk_overlap', None),
            )
            results.append({"id": f.id, "filename": f.filename, "status": "ok", "chunks": r.get("chunks", 0)})
        except Exception as e:
            results.append({"id": f.id, "filename": f.filename, "status": "error", "error": str(e)[:200]})

    ok_count = sum(1 for r in results if r["status"] == "ok")
    err_count = sum(1 for r in results if r["status"] == "error")
    return {"message": f"索引完成: {ok_count} 成功, {err_count} 失败", "count": len(results), "results": results}


# ── 语义搜索 ────────────────────────────────────────────────────

@router.post("/search")
async def search_knowledge(req: SearchRequest, db: Session = Depends(get_db)):
    """语义搜索知识库（支持按知识库筛选）"""
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="查询内容不能为空")
    indexer = Indexer(db)
    try:
        results = indexer.search_chunks(req.query, req.top_k, req.kb_id)
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


@router.get("/kb")
async def list_knowledge_bases(db: Session = Depends(get_db)):
    """列出所有知识库分类"""
    svc = KnowledgeBaseService(db)
    kbs = svc.get_all()
    return {"knowledge_bases": [{"id": k.id, "name": k.name, "description": k.description,
            "is_active": k.is_active, "created_at": k.created_at.isoformat() if k.created_at else ""} for k in kbs]}


@router.post("/kb")
async def create_knowledge_base(data: KBCreate, db: Session = Depends(get_db)):
    """创建知识库分类"""
    svc = KnowledgeBaseService(db)
    try:
        kb = svc.create(data.name, data.description)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"创建失败: {e}")
    return {"id": kb.id, "name": kb.name, "message": "创建成功"}


@router.put("/kb/{kb_id}")
async def update_knowledge_base(kb_id: int, data: KBUpdate, db: Session = Depends(get_db)):
    svc = KnowledgeBaseService(db)
    kb = svc.update(kb_id, data.model_dump(exclude_none=True))
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return {"id": kb.id, "message": "更新成功"}


@router.delete("/kb/{kb_id}")
async def delete_knowledge_base(kb_id: int, db: Session = Depends(get_db)):
    svc = KnowledgeBaseService(db)
    if not svc.delete(kb_id):
        raise HTTPException(status_code=404, detail="知识库不存在")
    return {"message": "删除成功"}


@router.put("/files/{file_id}/move")
async def move_file_to_kb(file_id: int, data: FileMoveRequest, db: Session = Depends(get_db)):
    """将文件移动到指定知识库"""
    from app.core.database import KnowledgeFile
    f = db.query(KnowledgeFile).filter(KnowledgeFile.id == file_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="文件不存在")
    f.kb_id = data.kb_id
    db.commit()
    kb_name = "通用"
    if data.kb_id:
        kb = KnowledgeBaseService(db).get_by_id(data.kb_id)
        kb_name = kb.name if kb else str(data.kb_id)
    return {"message": f"已移至: {kb_name}", "kb_id": data.kb_id}
