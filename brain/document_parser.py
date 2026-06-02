"""
Parse PDF, DOCX, and images into text + extracted image files.
Returns ParsedDocument with text content and list of image paths saved to brain storage.
"""
import base64
import io
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ParsedDocument:
    text: str
    images: list[str] = field(default_factory=list)   # relative paths inside brain storage
    source_filename: str = ""
    page_count: int = 0
    error: Optional[str] = None


async def parse_pdf(file_bytes: bytes, filename: str, storage) -> ParsedDocument:
    """Extract text and images from PDF using pymupdf."""
    try:
        import fitz  # pymupdf

        doc = fitz.open(stream=file_bytes, filetype="pdf")
        text_parts = []
        image_paths = []

        for page_num, page in enumerate(doc):
            text = page.get_text("text").strip()
            if text:
                text_parts.append(f"--- Страница {page_num + 1} ---\n{text}")

            # Extract images from page
            for img_index, img in enumerate(page.get_images(full=True)):
                xref = img[0]
                base_image = doc.extract_image(xref)
                img_bytes = base_image["image"]
                img_ext = base_image["ext"]

                img_name = f"{uuid.uuid4().hex[:8]}.{img_ext}"
                img_rel_path = f"attachments/{img_name}"
                storage.write_file(img_rel_path, "", {})  # create dir
                img_abs = storage.root / img_rel_path
                img_abs.parent.mkdir(parents=True, exist_ok=True)
                img_abs.write_bytes(img_bytes)
                image_paths.append(img_rel_path)

        doc.close()
        return ParsedDocument(
            text="\n\n".join(text_parts),
            images=image_paths,
            source_filename=filename,
            page_count=len(doc),
        )
    except ImportError:
        return ParsedDocument(
            text="",
            error="pymupdf не установлен. Установи: pip install pymupdf",
            source_filename=filename,
        )
    except Exception as e:
        return ParsedDocument(text="", error=str(e), source_filename=filename)


async def parse_docx(file_bytes: bytes, filename: str, storage) -> ParsedDocument:
    """Extract text and images from DOCX."""
    try:
        from docx import Document
        from docx.oxml.ns import qn

        doc = Document(io.BytesIO(file_bytes))
        text_parts = []
        image_paths = []

        for para in doc.paragraphs:
            if para.text.strip():
                text_parts.append(para.text.strip())

        # Tables
        for table in doc.tables:
            rows = []
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                rows.append(" | ".join(cells))
            if rows:
                text_parts.append("\n".join(rows))

        # Images from relationships
        for rel in doc.part.rels.values():
            if "image" in rel.reltype:
                img_bytes = rel.target_part.blob
                ext = rel.target_part.content_type.split("/")[-1]
                if ext in ("jpeg", "jpg", "png", "gif", "webp"):
                    img_name = f"{uuid.uuid4().hex[:8]}.{ext}"
                    img_rel_path = f"attachments/{img_name}"
                    img_abs = storage.root / img_rel_path
                    img_abs.parent.mkdir(parents=True, exist_ok=True)
                    img_abs.write_bytes(img_bytes)
                    image_paths.append(img_rel_path)

        return ParsedDocument(
            text="\n\n".join(text_parts),
            images=image_paths,
            source_filename=filename,
        )
    except ImportError:
        return ParsedDocument(
            text="",
            error="python-docx не установлен.",
            source_filename=filename,
        )
    except Exception as e:
        return ParsedDocument(text="", error=str(e), source_filename=filename)


async def parse_image(file_bytes: bytes, filename: str, storage, user_id: str) -> ParsedDocument:
    """Use Claude Vision to extract text/description from image, save image to storage."""
    from core.claude import call_claude_vision

    # Save image to attachments
    ext = Path(filename).suffix.lstrip(".") or "jpg"
    img_name = f"{uuid.uuid4().hex[:8]}.{ext}"
    img_rel_path = f"attachments/{img_name}"
    img_abs = storage.root / img_rel_path
    img_abs.parent.mkdir(parents=True, exist_ok=True)
    img_abs.write_bytes(file_bytes)

    # Ask Claude to describe / extract text
    b64 = base64.standard_b64encode(file_bytes).decode()
    media_type = _get_media_type(ext)

    text, _ = await call_claude_vision(
        system=(
            "Ты помощник для извлечения знаний из изображений. "
            "Опиши что на изображении подробно: если есть текст — перепиши его полностью. "
            "Если это схема/диаграмма — объясни что она показывает. "
            "Если фото встречи/доски — перепиши все записи. "
            "Отвечай на русском."
        ),
        image_b64=b64,
        media_type=media_type,
        user_id=user_id,
    )

    return ParsedDocument(
        text=text,
        images=[img_rel_path],
        source_filename=filename,
    )


def _get_media_type(ext: str) -> str:
    return {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "webp": "image/webp",
    }.get(ext.lower(), "image/jpeg")


async def parse_document(
    file_bytes: bytes,
    filename: str,
    storage,
    user_id: str,
) -> ParsedDocument:
    """Route to correct parser based on file extension."""
    ext = Path(filename).suffix.lower()

    if ext == ".pdf":
        return await parse_pdf(file_bytes, filename, storage)
    elif ext in (".docx", ".doc"):
        return await parse_docx(file_bytes, filename, storage)
    elif ext in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
        return await parse_image(file_bytes, filename, storage, user_id)
    else:
        # Try to read as plain text
        try:
            text = file_bytes.decode("utf-8", errors="replace")
            return ParsedDocument(text=text, source_filename=filename)
        except Exception:
            return ParsedDocument(
                text="",
                error=f"Неизвестный формат: {ext}",
                source_filename=filename,
            )


def format_images_for_obsidian(image_paths: list[str], base_text: str) -> str:
    """Append Obsidian image embeds to note body."""
    if not image_paths:
        return base_text

    img_section = "\n\n## Вложения\n"
    for path in image_paths:
        filename = Path(path).name
        img_section += f"\n![[{filename}]]"

    return base_text + img_section
