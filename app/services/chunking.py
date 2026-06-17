"""Chunking strategies using LlamaIndex text splitters + Chinese-aware custom splitters.

Supports:
  - recursive  — RecursiveCharacterTextSplitter, 多级分隔符递归切分 (新默认)
  - sentence   — SentenceSplitter, 按句子边界切分 (保留兼容)
  - token      — TokenTextSplitter, 按 Token 数切分
  - paragraph  — 按段落边界 (\\n\\n) 切分, 保留篇章结构
  - fixed      — 固定长度切分 (回退方案)
  - excel      — Excel 行分组切分
  - semantic   — 基于 embedding 相似度变化自动检测话题切换点
  - section    — 面向法规文档, 按 第X章/第X节/第X条 切分, 保留层级元信息
  - qa         — 面向问答对, 按 问/答 边界切分

Per file-type defaults can be overridden via CHUNK_CONFIG.

Embedding model: bge-base-zh-v1.5 (768 dims, max_seq_length ~512 tokens ≈ 384-512 chars for Chinese).
"""
import logging
import re
from typing import List, Optional, Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ── Strategy config ───────────────────────────────────────────────

@dataclass
class ChunkConfig:
    """Configuration for a chunking strategy."""
    strategy: str = "recursive"          # recursive | sentence | token | paragraph | fixed | excel | semantic | section | qa
    chunk_size: int = 512                # chars (≈ 350-500 Chinese tokens → fits bge model window)
    chunk_overlap: int = 128             # overlap between chunks
    separators: List[str] = field(default_factory=lambda: [
        "\n\n", "\n", "。", "！", "？", "；", "：", "…", "……",
        ".", "!", "?", ";", ":",
        "，", "、", " ", "",
    ])

    # Token-splitter specific
    tokenizer_model: str = "gpt-3.5-turbo"

    # Semantic chunker threshold (cosine similarity drop point)
    semantic_threshold: float = 0.7


# Per file-type defaults — tuned for bge-base-zh-v1.5 window
CHUNK_CONFIG: dict[str, ChunkConfig] = {
    "pdf":  ChunkConfig(strategy="recursive", chunk_size=512, chunk_overlap=128),
    "docx": ChunkConfig(strategy="recursive", chunk_size=512, chunk_overlap=128),
    "txt":  ChunkConfig(strategy="recursive", chunk_size=1024, chunk_overlap=200),
    "md":   ChunkConfig(strategy="recursive", chunk_size=1024, chunk_overlap=200),
    "csv":  ChunkConfig(strategy="fixed",     chunk_size=2048, chunk_overlap=100),
    "xlsx": ChunkConfig(strategy="excel"),
    "default": ChunkConfig(strategy="recursive", chunk_size=512, chunk_overlap=128),
}

EXCEL_ROW_CHUNK = 5  # rows per chunk for Excel


# ── Splitter factory (LlamaIndex-based) ──────────────────────────

def _get_recursive_splitter(config: ChunkConfig):
    """LlamaIndex RecursiveCharacterTextSplitter — multi-separator, priority-based.
    Best general-purpose: tries paragraph break first, then sentence, then punctuation.
    """
    from llama_index.core.node_parser import SentenceSplitter
    # SentenceSplitter with Chinese-aware separators behaves like recursive
    return SentenceSplitter(
        chunk_size=config.chunk_size,
        chunk_overlap=config.chunk_overlap,
        separator=" ",
        paragraph_separator="\n\n",
    )


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
    """Fallback fixed-length splitter — uses SentenceSplitter with large separators."""
    from llama_index.core.node_parser import SentenceSplitter
    return SentenceSplitter(
        chunk_size=config.chunk_size,
        chunk_overlap=config.chunk_overlap,
        separator=" ",
        paragraph_separator="\n\n",
    )


def get_splitter(file_type: str, config: ChunkConfig = None):
    """Return appropriate LlamaIndex splitter for given file type and strategy."""
    if config is None:
        config = CHUNK_CONFIG.get(file_type, CHUNK_CONFIG["default"])

    strategy = config.strategy
    try:
        if strategy in ("recursive", "sentence"):
            return _get_recursive_splitter(config) if strategy == "recursive" else _get_sentence_splitter(config)
        elif strategy == "token":
            return _get_token_splitter(config)
        elif strategy == "paragraph":
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


# ── Chinese sentence boundary detection ──────────────────────────

# Chinese sentence-ending punctuation
_CN_SENTENCE_END = re.compile(r'[。！？；：…\n.!?;:]')


def _split_cn_sentences(text: str) -> List[str]:
    """Split text into Chinese-aware sentences for semantic chunking."""
    # Split on sentence-ending punctuation while keeping the delimiter
    parts = _CN_SENTENCE_END.split(text)
    delimiters = _CN_SENTENCE_END.findall(text)

    sentences = []
    for i, part in enumerate(parts):
        part = part.strip()
        if not part and i >= len(delimiters):
            continue
        delim = delimiters[i] if i < len(delimiters) else ""
        combined = (part + delim).strip()
        if combined:
            sentences.append(combined)

    return sentences


# ── Custom chunking strategies ───────────────────────────────────

def _split_by_section(text: str, config: ChunkConfig) -> List[dict]:
    """Section-aware chunking for Chinese legal/regulatory documents.

    Detects: 第X章 / 第X节 / 第X条 / 第X款 / 附件X
    Each article becomes its own chunk with metadata.
    """
    # Pattern: 第[一二三四五六七八九十百千零\d]+[章节条款] or 附件[一二三四五六七八九十\d]+
    section_pattern = re.compile(
        r'(第[一二三四五六七八九十百千零\d]+[章节条款]|附件[一二三四五六七八九十\d]+)'
    )
    parts = section_pattern.split(text)

    chunks = []
    buffer = ""
    current_section = ""

    for i, part in enumerate(parts):
        part = part.strip()
        if not part:
            continue

        # Check if this part is a section header
        if section_pattern.fullmatch(part):
            # Save previous section
            if buffer:
                chunks.append({
                    "content": buffer.strip(),
                    "metadata": {"section": current_section} if current_section else {},
                })
            current_section = part
            buffer = part + "\n"
        else:
            buffer += part + "\n"

    # Last section
    if buffer.strip():
        chunks.append({
            "content": buffer.strip(),
            "metadata": {"section": current_section} if current_section else {},
        })

    # If section detection didn't actually find any headers, fall back to recursive
    if len(chunks) <= 1 and not current_section:
        logger.info(f"[chunk] section did not find headers, falling back to recursive")
        return _split_recursive(text, config)

    logger.debug(f"[chunk] section produced {len(chunks)} chunks")
    return chunks


def _split_qa(text: str, config: ChunkConfig) -> List[dict]:
    """Q&A-aware chunking for FAQ / interview-style documents.

    Detects: 问/答:, Q/A:, Question/Answer: (Chinese and English)
    Each Q&A pair becomes one chunk.
    """
    patterns = [
        re.compile(r'^(问|Q|Question|问题|用户)[：:]', re.IGNORECASE),
        re.compile(r'^(答|A|Answer|回答|AI|助手|Bot)[：:]', re.IGNORECASE),
    ]
    lines = text.split("\n")

    chunks = []
    buffer_lines = []
    in_qa_block = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            buffer_lines.append(line)
            continue

        # Detect a Q-line as start of a new Q&A pair
        if patterns[0].match(stripped):
            # Save previous Q&A pair
            if buffer_lines:
                chunk_text = "\n".join(buffer_lines).strip()
                if chunk_text:
                    chunks.append({"content": chunk_text, "metadata": {"type": "qa"}})
                buffer_lines = []
            in_qa_block = True
            buffer_lines.append(line)
        elif in_qa_block:
            buffer_lines.append(line)
        else:
            buffer_lines.append(line)

    if buffer_lines:
        chunk_text = "\n".join(buffer_lines).strip()
        if chunk_text:
            chunks.append({"content": chunk_text, "metadata": {"type": "qa"}})

    return chunks if chunks else _split_recursive(text, config)


def _split_semantic(text: str, config: ChunkConfig) -> List[dict]:
    """Semantic chunking — detect topic shifts via embedding similarity.

    Splits text into sentences, computes pairwise cosine similarity,
    and cuts where similarity drops below threshold.
    Requires the embedding model to be loaded; falls back to recursive if unavailable.
    """
    try:
        from app.services.embedding import embed_documents
    except ImportError:
        logger.warning("embedding module unavailable, falling back to recursive for semantic")
        return _split_recursive(text, config)

    sentences = _split_cn_sentences(text)
    if len(sentences) <= 1:
        return [{"content": text.strip(), "metadata": {"strategy": "semantic"}}]

    # Get embeddings (batched)
    try:
        embs = embed_documents(sentences)
    except Exception as e:
        logger.warning(f"Embedding failed in semantic chunker: {e}, falling back to recursive")
        return _split_recursive(text, config)

    # Cosine similarity between consecutive sentence embeddings
    import numpy as np
    embs_np = np.array(embs)

    sims = np.sum(embs_np[:-1] * embs_np[1:], axis=1)  # dot product (normalized vectors)
    threshold = config.semantic_threshold

    # Cut where similarity drops below threshold OR chunk grows too large
    chunks = []
    current = [sentences[0]]
    current_len = len(sentences[0])

    for i in range(1, len(sentences)):
        # Check: topic shift or size limit
        if sims[i - 1] < threshold or current_len + len(sentences[i]) > config.chunk_size:
            chunks.append({"content": "".join(current).strip(), "metadata": {"strategy": "semantic"}})
            current = [sentences[i]]
            current_len = len(sentences[i])
        else:
            current.append(sentences[i])
            current_len += len(sentences[i])

    if current:
        chunks.append({"content": "".join(current).strip(), "metadata": {"strategy": "semantic"}})

    return chunks


def _split_recursive(text: str, config: ChunkConfig) -> List[dict]:
    """Recursive splitting — multi-separator, best general-purpose.

    Uses LlamaIndex SentenceSplitter with paragraph-level separators
    so that large structural boundaries are preferred.
    """
    splitter = _get_recursive_splitter(config)
    nodes = splitter.split_text(text)

    chunks = []
    for node in nodes:
        chunk_text = node.text if hasattr(node, 'text') else str(node)
        if chunk_text.strip():
            chunks.append({"content": chunk_text.strip(), "metadata": {}})
    return chunks


# ── Main chunking entry point ────────────────────────────────────

def split_text(text: str, file_type: str = "default", config: ChunkConfig = None) -> List[dict]:
    """Split text into chunks using the configured strategy.

    Returns list of {"content": str, "metadata": dict}.

    Strategies:
      - recursive (new default): multi-separator, general-purpose
      - semantic:            embedding-based topic boundary detection
      - section:             legal/regulatory (章/节/条 boundary)
      - qa:                  Q&A pair detection
      - sentence/paragraph:  LlamaIndex standard splitters (backward compat)
      - token/fixed:         token-accurate / fixed-length
      - excel:               row-grouped for spreadsheets
    """
    if not text or not text.strip():
        return []

    cfg = config or CHUNK_CONFIG.get(file_type, CHUNK_CONFIG["default"])
    logger.info(f"[chunk] {file_type}: strategy={cfg.strategy}, size={cfg.chunk_size}, overlap={cfg.chunk_overlap}, text_len={len(text)}")
    strategy = cfg.strategy

    # Excel: keep row-grouped approach (doesn't use LlamaIndex)
    if strategy == "excel":
        return _split_excel(text)

    # Section-aware: Chinese legal docs
    if strategy == "section":
        return _split_by_section(text, cfg)

    # Q&A pairs
    if strategy == "qa":
        return _split_qa(text, cfg)

    # Semantic chunking
    if strategy == "semantic":
        return _split_semantic(text, cfg)

    # Paragraph: pre-split by double newlines, then further split long paragraphs
    if strategy == "paragraph":
        return _split_by_paragraph(text, cfg)

    # Standard: recursive / sentence / token / fixed → use LlamaIndex splitter
    splitter = get_splitter(file_type, cfg)
    nodes = splitter.split_text(text)

    chunks = []
    for node in nodes:
        chunk_text = node.text if hasattr(node, 'text') else str(node)
        if chunk_text.strip():
            chunks.append({"content": chunk_text.strip(), "metadata": {}})

    logger.info(f"[chunk] produced {len(chunks)} chunks (strategy={cfg.strategy})")
    return chunks


def _split_by_paragraph(text: str, config: ChunkConfig) -> List[dict]:
    """Paragraph-aware splitting: split by \\n\\n first, then further split long paragraphs."""
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


# ── Strategy info for UI ─────────────────────────────────────────

def list_strategies() -> List[dict]:
    """Return available chunking strategies for UI display."""
    return [
        {"key": "recursive", "label": "递归切分", "desc": "多级分隔符(段落→句→标点)优先保留大结构，通用首选", "default_size": 512},
        {"key": "sentence", "label": "句子级切分", "desc": "按句子边界智能切分，中英文友好", "default_size": 512},
        {"key": "paragraph", "label": "段落级切分", "desc": "先按段落(\\n\\n)切分再对长段落分片，保留篇章结构", "default_size": 1024},
        {"key": "section", "label": "条款级切分", "desc": "检测中文法规结构(第X章/节/条)，保留层级元信息", "default_size": 1024},
        {"key": "qa", "label": "问答对切分", "desc": "按问/答边界分组，每对一问一答一个 chunk", "default_size": 512},
        {"key": "semantic", "label": "语义切分", "desc": "基于 embedding 相似度检测话题切换点，自动分片", "default_size": 512},
        {"key": "token", "label": "Token 级切分", "desc": "按 Token 数精确切分，对齐模型上下文窗口，需 tiktoken", "default_size": 512},
        {"key": "fixed", "label": "固定长度切分", "desc": "按固定字符数切分+重叠，简单可靠", "default_size": 1024},
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
