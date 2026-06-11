"""知识库文件上传/下载 API - MinIO"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.logging import logger
from app.services.knowledge import KnowledgeService
from minio.error import S3Error
from urllib.parse import quote
import io

router = APIRouter()


def _to_file_info(f) -> dict:
    return {
        "id": f.id,
        "filename": f.filename,
        "file_type": f.file_type,
        "file_size": f.file_size,
        "status": f.status,
        "chunk_count": f.chunk_count,
        "error_msg": f.error_msg,
        "uploader": f.uploader or "anonymous",
        "created_at": f.created_at.isoformat() if f.created_at else ""
    }


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
async def upload_file(file: UploadFile = File(...), db: Session = Depends(get_db)):
    svc = KnowledgeService(db)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")
    try:
        record = svc.save_upload(content, file.filename or "unknown")
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
