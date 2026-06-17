"""Document indexing service — splits, embeds, and stores in pgvector.

Powered by LlamaIndex text splitters + Chinese-aware custom splitters:
  - recursive  — 多级分隔符递归切分 (新默认, 通用首选)
  - sentence   — 句子级智能切分 (PDF/DOCX)
  - paragraph  — 按段落切分, 保留篇章结构 (MD/TXT)
  - token      — Token 级切分, 对齐模型上下文窗口
  - fixed      — 固定长度切分 (CSV 等)
  - excel      — Excel 行分组切分
  - section    — 面向法规文档, 按章/节/条切分
  - qa         — 面向问答对, 按问/答边界分组
  - semantic   — 基于 embedding 相似度的语义切分

Embedding model: BAAI/bge-base-zh-v1.5 (768 dims)."""
import io
import json
import logging
from typing import List
from sqlalchemy.orm import Session

from app.core.database import KnowledgeFile, DocumentChunk
from app.core.settings import settings
from app.services.knowledge import KnowledgeService
from app.services.embedding import embed_texts, embed_query
from app.services.chunking import split_text, CHUNK_CONFIG

logger = logging.getLogger(__name__)


class Indexer:
    """Handles document loading, splitting, embedding, and pgvector storage."""

    def __init__(self, db: Session):
        self.db = db
        self.knowledge_svc = KnowledgeService(db)

    def index_file(self, file_id: int, strategy: str = None, chunk_size: int = None, chunk_overlap: int = None) -> dict:
        """Index a single file: load → split → embed → store.

        Optionally override chunking strategy/size/overlap per call.
        """
        record = self.db.query(KnowledgeFile).filter(KnowledgeFile.id == file_id).first()
        if not record:
            return {"error": "文件不存在"}

        try:
            record.status = "indexing"
            record.error_msg = None
            self.db.commit()

            # 1. Load content from MinIO
            import time
            t0 = time.time()
            content_bytes, _, _ = self.knowledge_svc.get_file_content(file_id)
            text = self._parse_content(content_bytes, record.filename, record.file_type)
            parse_time = time.time() - t0
            logger.info(f"[index] file={record.filename} (id={file_id}, type={record.file_type}, "
                        f"size={record.file_size}B), parsed {len(text)} chars in {parse_time:.1f}s")

            # 1.5 Validate content quality — reject binary garbage
            err = self._validate_content(text, record.filename)
            if err:
                record.status = "error"
                record.error_msg = err
                self.db.commit()
                return {"error": err}

            # 2. Get chunk config for this file type (with optional overrides)
            from app.services.chunking import ChunkConfig
            cfg = CHUNK_CONFIG.get(record.file_type, CHUNK_CONFIG["default"])
            effective_config = ChunkConfig(
                strategy=strategy or cfg.strategy,
                chunk_size=chunk_size or cfg.chunk_size,
                chunk_overlap=chunk_overlap or cfg.chunk_overlap,
            )

            # 3. Split into chunks using LlamaIndex strategy
            chunks = split_text(text, record.file_type, config=effective_config)

            if not chunks:
                record.status = "error"
                record.error_msg = "文档内容为空，无法分片"
                self.db.commit()
                return {"error": "文档内容为空"}

            # 4. Delete old chunks
            self.db.query(DocumentChunk).filter(DocumentChunk.file_id == file_id).delete()

            # 5. Generate embeddings and store
            texts = [c["content"] for c in chunks]
            logger.info(f"Generating embeddings for {len(texts)} chunks "
                        f"(strategy={effective_config.strategy}, size={effective_config.chunk_size}, "
                        f"overlap={effective_config.chunk_overlap})...")
            embeddings = embed_texts(texts)

            for i, chunk in enumerate(chunks):
                metadata = chunk.get("metadata", {})
                metadata["chunk_strategy"] = effective_config.strategy
                metadata["chunk_size"] = effective_config.chunk_size
                metadata["chunk_overlap"] = effective_config.chunk_overlap
                dc = DocumentChunk(
                    file_id=file_id,
                    chunk_index=i,
                    content=chunk["content"],
                    embedding=embeddings[i],
                    metadata_json=json.dumps(metadata, ensure_ascii=False),
                )
                self.db.add(dc)

            # 6. Update status
            record.status = "indexed"
            record.chunk_count = len(chunks)
            record.error_msg = None
            self.db.commit()

            logger.info(f"Indexed file {file_id}: {len(chunks)} chunks (strategy={effective_config.strategy})")
            return {"success": True, "chunks": len(chunks), "strategy": effective_config.strategy}

        except Exception as e:
            logger.error(f"Failed to index file {file_id}: {e}")
            record.status = "error"
            record.error_msg = str(e)
            self.db.commit()
            raise

    def _parse_content(self, content: bytes, filename: str, file_type: str) -> str:
        """Parse file bytes into plain text."""
        ext = file_type
        logger.debug(f"[parse] {filename}: type={ext}, bytes={len(content)}")

        text = ""
        if ext in ("txt", "md", "csv"):
            text = content.decode("utf-8", errors="replace")
            logger.debug(f"[parse] {filename}: decoded as text, {len(text)} chars")

        elif ext == "pdf":
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(content))
            pages = []
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    pages.append(t)
            text = "\n\n".join(pages)
            logger.debug(f"[parse] {filename}: PDF parsed, {len(reader.pages)} pages, {len(text)} chars")

        elif ext == "xlsx":
            try:
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
                text = "\n".join(rows)
                logger.debug(f"[parse] {filename}: XLSX parsed, {len(wb.sheetnames)} sheets, {len(rows)} rows, {len(text)} chars")
            except Exception as e:
                logger.warning(f"[parse] {filename}: XLSX parse failed: {e}, falling back to text decode")
                text = content.decode("utf-8", errors="replace")

        elif ext == "docx":
            try:
                from docx import Document
                doc = Document(io.BytesIO(content))
                text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
                logger.debug(f"[parse] {filename}: DOCX parsed, {len(doc.paragraphs)} paragraphs, {len(text)} chars")
            except ImportError:
                logger.warning(f"[parse] {filename}: python-docx not installed")
                text = ""
            except Exception as e:
                logger.warning(f"[parse] {filename}: DOCX parse failed: {e}, falling back to text decode")
                text = content.decode("utf-8", errors="replace")

        else:
            logger.warning(f"[parse] {filename}: unknown type '{ext}', raw decode")
            text = content.decode("utf-8", errors="replace")

        # Strip NUL and non-printable control chars that break PostgreSQL
        text = text.replace("\x00", "").replace("\r", "\n")
        return text

    def _validate_content(self, text: str, filename: str) -> str | None:
        """Validate that parsed content looks like readable text, not binary garbage.

        Returns error message string if content is invalid, None if OK.
        """
        if not text or not text.strip():
            logger.warning(f"[validate] {filename}: empty content")
            return "文档解析后内容为空"

        total = len(text)
        printable = sum(
            1 for c in text
            if c.isprintable() or c in "\n\t\r" or
               ('\u4e00' <= c <= '\u9fff') or
               ('\u3000' <= c <= '\u303f') or
               ('\uff00' <= c <= '\uffef')
        )
        ratio = printable / total if total > 0 else 0
        logger.debug(f"[validate] {filename}: printable_ratio={ratio:.1%}, total_chars={total}")

        if ratio < 0.5:
            logger.warning(f"[validate] {filename}: low printable ratio {ratio:.1%}, rejecting")
            return f"文件内容可读率仅 {ratio:.1%}，可能是二进制文件或加密文件"

        return None

    def search_chunks(self, query: str, top_k: int = 5, kb_id: int = None) -> List[dict]:
        """Search document chunks by semantic similarity, optionally scoped to a KB."""
        from sqlalchemy import text

        logger.info(f"[search] query: {query[:80]}..., top_k={top_k}, kb_id={kb_id}")
        query_embedding = embed_query(query)
        embedding_str = "[" + ",".join(str(v) for v in query_embedding) + "]"

        if kb_id:
            sql = text("""
                SELECT dc.id, dc.content, dc.metadata_json, dc.chunk_index,
                       kf.filename, kf.file_type,
                       1 - (dc.embedding <=> :embedding) AS similarity
                FROM document_chunks dc
                JOIN knowledge_files kf ON dc.file_id = kf.id
                WHERE kf.kb_id = :kb_id
                ORDER BY dc.embedding <=> :embedding
                LIMIT :limit
            """)
            result = self.db.execute(sql, {"embedding": embedding_str, "limit": top_k, "kb_id": kb_id})
        else:
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

        if rows:
            sims = [r["similarity"] for r in rows]
            logger.info(f"[search] {len(rows)} results, sims=[{', '.join(f'{s:.3f}' for s in sims)}], "
                        f"top_sim={sims[0]:.3f}, files={list(set(r['filename'] for r in rows))}")
        else:
            logger.warning(f"[search] no results for query: {query[:80]}")
        return rows
