"""PDF → DOCX conversion skill using pdf2docx library.

Converts PDF files to editable DOCX format, which often yields better
text extraction quality via python-docx than raw pypdf extraction,
especially for documents with complex layouts, tables, or mixed fonts.
"""
import io
import logging
import tempfile
import os

from app.services.skill_base import BaseSkill, register_skill

logger = logging.getLogger(__name__)


@register_skill
class PdfToDocxSkill(BaseSkill):
    name = "pdf_to_docx"
    description = "将 PDF 文档转换为可编辑的 DOCX 格式，提升复杂排版文档的文本提取质量"
    input_types = ["pdf"]
    output_type = "docx"

    def process(self, content: bytes, filename: str) -> tuple[bytes, str, str]:
        """Convert PDF bytes to DOCX bytes.

        Uses pdf2docx to parse PDF pages and write a single DOCX file.
        Falls back gracefully: if pdf2docx is unavailable, returns the
        original content with an error logged.
        """
        try:
            from pdf2docx import Converter
        except ImportError:
            logger.error(
                "pdf2docx library not installed. "
                "Install with: uv add pdf2docx  or  pip install pdf2docx"
            )
            raise RuntimeError(
                "PDF→DOCX conversion requires pdf2docx. "
                "Install it with: pip install pdf2docx"
            )

        # pdf2docx works with file paths, so write to temp files
        pdf_path = None
        docx_path = None

        try:
            # Write PDF bytes to temp file
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_pdf:
                tmp_pdf.write(content)
                pdf_path = tmp_pdf.name

            # Create temp path for output DOCX
            docx_fd, docx_path = tempfile.mkstemp(suffix=".docx")
            os.close(docx_fd)

            # Convert
            cv = Converter(pdf_path)
            cv.convert(docx_path, start=0, end=None)
            cv.close()

            # Read back the DOCX bytes
            with open(docx_path, "rb") as f:
                docx_bytes = f.read()

            # Generate new filename
            base = filename.rsplit(".", 1)[0] if "." in filename else filename
            new_filename = f"{base}.docx"

            logger.info(
                f"PDF→DOCX: {filename} ({len(content)} bytes) "
                f"→ {new_filename} ({len(docx_bytes)} bytes)"
            )
            return docx_bytes, new_filename, "docx"

        except Exception as e:
            logger.error(f"PDF→DOCX conversion failed for {filename}: {e}")
            raise RuntimeError(f"PDF→DOCX conversion failed: {e}") from e

        finally:
            # Clean up temp files
            if pdf_path and os.path.exists(pdf_path):
                try:
                    os.unlink(pdf_path)
                except OSError:
                    pass
            if docx_path and os.path.exists(docx_path):
                try:
                    os.unlink(docx_path)
                except OSError:
                    pass
