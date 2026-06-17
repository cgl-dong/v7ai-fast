"""
迁移步骤：将 document_chunks.embedding 从 384 维改为 768 维。

⚠️ 会清除所有已有 embedding 数据，需要重新索引所有文件。

pgvector 不支持 ALTER COLUMN TYPE 改变向量维度（除非表为空），
因此采用：删列 → 重建列 → 重建索引的方式。
"""

MIGRATION_SQL = """
-- ============================================================
-- Migration: embedding 384 → 768 维 (bge-base-zh-v1.5)
-- ============================================================

-- 1. 新增分片策略字段
ALTER TABLE knowledge_files
    ADD COLUMN IF NOT EXISTS chunk_strategy VARCHAR(20),
    ADD COLUMN IF NOT EXISTS chunk_size INTEGER,
    ADD COLUMN IF NOT EXISTS chunk_overlap INTEGER;

-- 2. 删除旧的 embedding 列
ALTER TABLE document_chunks DROP COLUMN IF EXISTS embedding;

-- 3. 删除旧的向量索引（如果存在）
DROP INDEX IF EXISTS idx_document_chunks_embedding;

-- 4. 重建 embedding 列（768 维）
ALTER TABLE document_chunks ADD COLUMN embedding vector(768);

-- 5. 重建 ivfflat 索引（适合 10万级数据，索引大小约 ~2× 数据大小）
--    列表数 = sqrt(行数) → 数据量少时用 10, 百万级用 1000
CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding
    ON document_chunks
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 10);

-- ============================================================
-- [可选] 如果数据量超过 10万行，改用 HNSW 索引（更精确但建索引更慢）
-- ============================================================
-- DROP INDEX IF EXISTS idx_document_chunks_embedding;
-- CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding_hnsw
--     ON document_chunks
--     USING hnsw (embedding vector_cosine_ops)
--     WITH (m = 16, ef_construction = 200);
"""

if __name__ == "__main__":
    # 快捷执行：python -m app.core.migrate_embedding
    import sys
    from app.core.database import engine

    print("正在执行 embedding 迁移（384→768 维）...")
    print("⚠️  将清除所有已有 embedding 数据！\n")

    # 逐条执行
    for stmt in MIGRATION_SQL.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            print(f"执行: {stmt[:80]}...")
            with engine.connect() as conn:
                conn.execute(stmt)
                conn.commit()

    print("\n✅ 迁移完成。请重新索引所有文档。")
    print("   运行: curl -X POST http://localhost:18081/api/v1/knowledge/files/index-all")
