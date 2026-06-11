"""Document indexing service — splits, embeds, and stores in pgvector."""
import io
import json
import logging
from typing import List
from sqlalchemy.orm import Session

from app.core.database import KnowledgeFile, DocumentChunk
from app.core.settings import settings
from app.services.knowledge import KnowledgeService
from app.services.embedding import embed_texts

logger = logging.getLogger(__name__)

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200
EXCEL_ROW_CHUNK = 5


class Indexer:
    """Handles document loading, splitting, embedding, and pgvector storage."""

    def __init__(self, db: Session):
        self.db = db
        self.knowledge_svc = KnowledgeService(db)

    def index_file(self, file_id: int) -> dict:
        """Index a single file: load → split → embed → store."""
        record = self.db.query(KnowledgeFile).filter(KnowledgeFile.id == file_id).first()
        if not record:
            return {"error": "文件不存在"}

        try:
            record.status = "indexing"
            record.error_msg = None
            self.db.commit()

            # 1. Load content from MinIO
            content_bytes, _, _ = self.knowledge_svc.get_file_content(file_id)
            text = self._parse_content(content_bytes, record.filename, record.file_type)

            # 2. Split into chunks
            chunks = self._split_text(text, record.file_type)

            if not chunks:
                record.status = "error"
                record.error_msg = "文档内容为空，无法分片"
                self.db.commit()
                return {"error": "文档内容为空"}

            # 3. Delete old chunks
            self.db.query(DocumentChunk).filter(DocumentChunk.file_id == file_id).delete()

            # 4. Generate embeddings and store
            texts = [c["content"] for c in chunks]
            logger.info(f"Generating embeddings for {len(texts)} chunks...")
            embeddings = embed_texts(texts)

            for i, chunk in enumerate(chunks):
                dc = DocumentChunk(
                    file_id=file_id,
                    chunk_index=i,
                    content=chunk["content"],
                    embedding=embeddings[i],
                    metadata_json=json.dumps(chunk.get("metadata", {}), ensure_ascii=False),
                )
                self.db.add(dc)

            # 5. Update status
            record.status = "indexed"
            record.chunk_count = len(chunks)
            record.error_msg = None
            self.db.commit()

            logger.info(f"Indexed file {file_id}: {len(chunks)} chunks")
            return {"success": True, "chunks": len(chunks)}

        except Exception as e:
            logger.error(f"Failed to index file {file_id}: {e}")
            record.status = "error"
            record.error_msg = str(e)
            self.db.commit()
            raise

    def _parse_content(self, content: bytes, filename: str, file_type: str) -> str:
        """Parse file bytes into plain text."""
        ext = file_type

        if ext in ("txt", "md", "csv"):
            return content.decode("utf-8", errors="replace")

        if ext == "pdf":
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(content))
            pages = []
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    pages.append(t)
            return "\n\n".join(pages)

        if ext == "xlsx":
            from openpyxl import load_workbook
            wb = load_workbook(io.BytesIO(content), read_only=True)
            rows = []
            for sheet_name in wb.sheetnames:
                sheet = wb[sheet_name]
                rows.append(f"[Sheet: {sheet_name}]")
                for row in sheet.iter_rows(values_only=True):
                    row_str = "\t".join(str(c) if c is not None else "" for c in row)
                    if row_str.strip():
                        rows.append(row_str)
            wb.close()
            return "\n".join(rows)

        if ext == "docx":
            try:
                from docx import Document
                doc = Document(io.BytesIO(content))
                return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            except ImportError:
                return f"[无法解析 DOCX 文件: 缺少 python-docx 依赖]"

        return content.decode("utf-8", errors="replace")

    def _split_text(self, text: str, file_type: str) -> List[dict]:
        """Split text into chunks by file type."""
        if not text.strip():
            return []

        if file_type == "xlsx":
            return self._split_excel(text)

        # General text splitting
        chunks = []
        start = 0
        while start < len(text):
            end = min(start + CHUNK_SIZE, len(text))
            chunk_text = text[start:end]
            if chunk_text.strip():
                chunks.append({"content": chunk_text, "metadata": {}})
            start += CHUNK_SIZE - CHUNK_OVERLAP
        return chunks

    def _split_excel(self, text: str) -> List[dict]:
        """Split Excel content row-by-row, grouping by 5 rows."""
        lines = [l for l in text.split("\n") if l.strip()]
        chunks = []
        for i in range(0, len(lines), EXCEL_ROW_CHUNK - 1):
            group = lines[i:i + EXCEL_ROW_CHUNK]
            if group:
                chunks.append({"content": "\n".join(group), "metadata": {}})
        return chunks

    def search_chunks(self, query: str, top_k: int = 5) -> List[dict]:
        """Search document chunks by semantic similarity."""
        from sqlalchemy import text

        query_embedding = embed_texts([query])[0]
        embedding_str = "[" + ",".join(str(v) for v in query_embedding) + "]"

        sql = text("""
            SELECT dc.id, dc.content, dc.metadata_json, dc.chunk_index,
                   kf.filename, kf.file_type,
                   1 - (dc.embedding <=> :embedding) AS similarity
            FROM document_chunks dc
            JOIN knowledge_files kf ON dc.file_id = kf.id
            ORDER BY dc.embedding <=> :embedding
            LIMIT :limit
        """)

        result = self.db.execute(sql, {"embedding": embedding_str, "limit": top_k})
        rows = []
        for r in result:
            rows.append({
                "id": r.id,
                "content": r.content,
                "filename": r.filename,
                "file_type": r.file_type,
                "chunk_index": r.chunk_index,
                "similarity": float(r.similarity),
                "metadata": json.loads(r.metadata_json) if r.metadata_json else {},
            })
        return rows
