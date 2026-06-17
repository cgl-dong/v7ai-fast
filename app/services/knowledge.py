"""知识库文件管理服务 - MinIO 对象存储"""
import io
import logging
import uuid
from typing import Optional, List
from sqlalchemy.orm import Session
from minio import Minio
from minio.error import S3Error

from app.core.database import KnowledgeFile, DocumentChunk
from app.core.settings import settings

logger = logging.getLogger("v7ai-fast.knowledge")

ALLOWED_EXTENSIONS = {"txt", "pdf", "xlsx", "xls", "docx", "md", "csv"}

EXTENSION_TO_TYPE = {
    "txt": "txt", "pdf": "pdf", "xlsx": "xlsx", "xls": "xlsx",
    "docx": "docx", "md": "md", "csv": "csv"
}


class KnowledgeService:
    """知识库文件管理服务 - 基于 MinIO"""
    
    def __init__(self, db: Session):
        self.db = db
        self._client = None
    
    def _get_client(self) -> Minio:
        if self._client is None:
            self._client = Minio(
                endpoint=settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=settings.minio_secure,
            )
            if not self._client.bucket_exists(settings.minio_bucket):
                self._client.make_bucket(settings.minio_bucket)
        return self._client
    
    def get_all_files(self, file_type: str = None, status: str = None) -> List[KnowledgeFile]:
        q = self.db.query(KnowledgeFile)
        if file_type:
            q = q.filter(KnowledgeFile.file_type == file_type)
        if status:
            q = q.filter(KnowledgeFile.status == status)
        return q.order_by(KnowledgeFile.created_at.desc()).all()
    
    def get_file_by_id(self, file_id: int) -> Optional[KnowledgeFile]:
        return self.db.query(KnowledgeFile).filter(KnowledgeFile.id == file_id).first()
    
    def save_upload(self, file_content: bytes, original_name: str, uploader: str = "",
                    chunk_strategy: Optional[str] = None, chunk_size: Optional[int] = None,
                    chunk_overlap: Optional[int] = None) -> KnowledgeFile:
        ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError(f"不支持的文件类型: .{ext}，支持: {', '.join(ALLOWED_EXTENSIONS)}")
        
        stored_name = f"{uuid.uuid4().hex}.{ext}"
        file_size = len(file_content)
        file_type = EXTENSION_TO_TYPE.get(ext, ext)
        
        client = self._get_client()
        client.put_object(
            bucket_name=settings.minio_bucket,
            object_name=stored_name,
            data=io.BytesIO(file_content),
            length=file_size,
            content_type="application/octet-stream"
        )
        
        record = KnowledgeFile(
            filename=original_name,
            stored_name=stored_name,
            file_type=file_type,
            file_size=file_size,
            file_path=stored_name,
            status="uploaded",
            uploader=uploader or "anonymous",
            chunk_strategy=chunk_strategy,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        logger.info(f"File uploaded: {original_name} ({file_type}, {file_size}B) -> id={record.id}")
        return record
    
    def get_file_content(self, file_id: int) -> tuple:
        record = self.get_file_by_id(file_id)
        if not record:
            raise FileNotFoundError("文件记录不存在")
        
        client = self._get_client()
        try:
            response = client.get_object(settings.minio_bucket, record.stored_name)
            content = response.read()
            response.close()
            response.release_conn()
            return content, record.filename, "application/octet-stream"
        except S3Error as e:
            raise FileNotFoundError(f"文件在 MinIO 中不存在: {e}")
    
    def delete_file(self, file_id: int) -> bool:
        record = self.get_file_by_id(file_id)
        if not record:
            return False
        
        client = self._get_client()
        try:
            client.remove_object(settings.minio_bucket, record.stored_name)
        except S3Error:
            pass
        
        # Delete chunks first
        self.db.query(DocumentChunk).filter(DocumentChunk.file_id == file_id).delete()
        self.db.delete(record)
        self.db.commit()
        logger.info(f"File deleted: id={file_id}, name={record.filename}")
        return True
    
    def get_file_stats(self) -> dict:
        total = self.db.query(KnowledgeFile).count()
        by_type = {}
        for ft in ["txt", "pdf", "xlsx", "docx", "md", "csv"]:
            count = self.db.query(KnowledgeFile).filter(KnowledgeFile.file_type == ft).count()
            if count > 0:
                by_type[ft] = count
        
        by_status = {}
        for s in ["uploaded", "indexed", "error"]:
            count = self.db.query(KnowledgeFile).filter(KnowledgeFile.status == s).count()
            by_status[s] = count
        
        return {"total": total, "by_type": by_type, "by_status": by_status}
