"""Chunking strategies using LlamaIndex text splitters.

Supports:
  - sentence  — SentenceSplitter, 按句子边界切分 (默认, 中英文友好)
  - token     — TokenTextSplitter, 按 Token 数切分 (需 tokenizer)
  - paragraph — 按段落边界 (\n\n) 切分, 保留篇章结构
  - fixed     — 原始固定长度切分 (回退方案)
  - excel     — Excel 行分组切分 (保留原逻辑)

Per file-type defaults can be set via CHUNK_CONFIG.
"""

import logging
from typing import List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ── Strategy config ───────────────────────────────────────────────

@dataclass
class ChunkConfig:
    """Configuration for a chunking strategy."""
    strategy: str = "sentence"      # sentence | token | paragraph | fixed | excel
    chunk_size: int = 1024          # chunk max size (chars for sentence/fixed, tokens for token)
    chunk_overlap: int = 200         # overlap between chunks
    separators: List[str] = field(default_factory=lambda: ["\n\n", "\n", "。", "！", "？", ".", "!", "?"])

    # Token-splitter specific
    tokenizer_model: str = "gpt-3.5-turbo"  # tiktoken model name


# Per file-type defaults
CHUNK_CONFIG: dict[str, ChunkConfig] = {
    "pdf":  ChunkConfig(strategy="sentence", chunk_size=1024, chunk_overlap=200),
    "docx": ChunkConfig(strategy="sentence", chunk_size=1024, chunk_overlap=200),
    "txt":  ChunkConfig(strategy="paragraph", chunk_size=2048, chunk_overlap=300),
    "md":   ChunkConfig(strategy="paragraph", chunk_size=2048, chunk_overlap=200),
    "csv":  ChunkConfig(strategy="fixed", chunk_size=2048, chunk_overlap=100),
    "xlsx": ChunkConfig(strategy="excel"),
    "default": ChunkConfig(strategy="sentence", chunk_size=1024, chunk_overlap=200),
}

EXCEL_ROW_CHUNK = 5  # rows per chunk for Excel


# ── Splitter factory ──────────────────────────────────────────────

def _get_sentence_splitter(config: ChunkConfig):
    """LlamaIndex SentenceSplitter — sentence-aware, best for mixed CN/EN text."""
    from llama_index.core.node_parser import SentenceSplitter
    return SentenceSplitter(
        chunk_size=config.chunk_size,
        chunk_overlap=config.chunk_overlap,
        separator=" ",
        paragraph_separator="\n\n",
    )


def _get_token_splitter(config: ChunkConfig):
    """LlamaIndex TokenTextSplitter — token-accurate, needs tiktoken."""
    from llama_index.core.node_parser import TokenTextSplitter
    return TokenTextSplitter(
        chunk_size=config.chunk_size,
        chunk_overlap=config.chunk_overlap,
        separator=" ",
    )


def _get_simple_splitter(config: ChunkConfig):
    """Fallback fixed-length splitter (no LlamaIndex dependency)."""
    from llama_index.core.text_splitter import SimpleTextSplitter
    return SimpleTextSplitter(
        chunk_size=config.chunk_size,
        chunk_overlap=config.chunk_overlap,
    )


def get_splitter(file_type: str, config: ChunkConfig = None):
    """Return appropriate LlamaIndex splitter for given file type and strategy."""
    if config is None:
        config = CHUNK_CONFIG.get(file_type, CHUNK_CONFIG["default"])

    strategy = config.strategy
    try:
        if strategy == "sentence":
            return _get_sentence_splitter(config)
        elif strategy == "token":
            return _get_token_splitter(config)
        elif strategy == "paragraph":
            # Paragraph strategy: split by \n\n first, then apply sentence splitter
            from llama_index.core.node_parser import SentenceSplitter
            return SentenceSplitter(
                chunk_size=config.chunk_size,
                chunk_overlap=config.chunk_overlap,
                separator="\n\n",  # prefer paragraph breaks
                paragraph_separator="\n\n",
            )
        else:  # fixed or unknown
            return _get_simple_splitter(config)
    except Exception as e:
        logger.warning(f"Failed to create {strategy} splitter for {file_type}: {e}, falling back to simple")
        return _get_simple_splitter(config)


# ── Chunking functions ────────────────────────────────────────────

def split_text(text: str, file_type: str = "default", config: ChunkConfig = None) -> List[dict]:
    """Split text into chunks using the configured strategy.

    Returns list of {"content": str, "metadata": dict}.
    """
    if not text or not text.strip():
        return []

    cfg = config or CHUNK_CONFIG.get(file_type, CHUNK_CONFIG["default"])

    # Excel: keep row-grouped approach
    if cfg.strategy == "excel":
        return _split_excel(text)

    # Paragraph: pre-split by double newlines to preserve structure,
    # then use LlamaIndex splitter per block
    if cfg.strategy == "paragraph":
        return _split_by_paragraph(text, cfg)

    # Standard: use LlamaIndex splitter
    splitter = get_splitter(file_type, cfg)
    nodes = splitter.split_text(text)

    chunks = []
    for node in nodes:
        # node could be a TextNode (has .text) or a string
        chunk_text = node.text if hasattr(node, 'text') else str(node)
        if chunk_text.strip():
            chunks.append({"content": chunk_text.strip(), "metadata": {}})
    return chunks


def _split_by_paragraph(text: str, config: ChunkConfig) -> List[dict]:
    """Paragraph-aware splitting: split by \n\n first, then further split long paragraphs."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    splitter = get_splitter("default", config)
    chunks = []
    metadata_index = 0
    for para in paragraphs:
        if len(para) <= config.chunk_size:
            chunks.append({"content": para, "metadata": {"para_index": metadata_index}})
            metadata_index += 1
        else:
            sub_nodes = splitter.split_text(para)
            for node in sub_nodes:
                chunk_text = node.text if hasattr(node, 'text') else str(node)
                if chunk_text.strip():
                    chunks.append({"content": chunk_text.strip(), "metadata": {"para_index": metadata_index}})
                    metadata_index += 1
    return chunks


def _split_excel(text: str, rows_per_chunk: int = None) -> List[dict]:
    """Excel row-grouped chunking."""
    if rows_per_chunk is None:
        rows_per_chunk = EXCEL_ROW_CHUNK
    lines = [l for l in text.split("\n") if l.strip()]
    chunks = []
    for i in range(0, len(lines), rows_per_chunk):
        group = lines[i:i + rows_per_chunk]
        if group:
            chunks.append({"content": "\n".join(group), "metadata": {}})
    return chunks


# ── Strategy info ─────────────────────────────────────────────────

def list_strategies() -> List[dict]:
    """Return available chunking strategies for UI display."""
    return [
        {"key": "sentence", "label": "句子级切分", "desc": "按句子边界智能切分，中英文友好，适合 PDF/DOCX 等文档", "default_size": 1024},
        {"key": "paragraph", "label": "段落级切分", "desc": "先按段落(\n\n)切分再对长段落分片，保留篇章结构，适合 MD/TXT", "default_size": 2048},
        {"key": "token", "label": "Token 级切分", "desc": "按 Token 数精确切分，对齐模型上下文窗口，需 tiktoken", "default_size": 512},
        {"key": "fixed", "label": "固定长度切分", "desc": "按固定字符数切分+重叠，简单可靠，适合 CSV 等结构化文本", "default_size": 2048},
        {"key": "excel", "label": "Excel 行分组", "desc": "按表格行分组，每 N 行一个 chunk", "default_size": 5},
    ]


def get_file_type_configs() -> dict:
    """Return current file-type → config mapping for UI display."""
    result = {}
    for ft, cfg in CHUNK_CONFIG.items():
        if ft == "default":
            continue
        result[ft] = {
            "strategy": cfg.strategy,
            "chunk_size": cfg.chunk_size,
            "chunk_overlap": cfg.chunk_overlap,
        }
    return result
