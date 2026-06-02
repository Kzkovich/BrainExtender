import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, TemplateNotFound, Undefined

from brain.classifier import ClassificationResult
from brain.linker import link_and_inject
from brain.profiles import Profile
from brain.storage import BrainStorage
from config.settings import settings
from core.claude import call_claude


class _SilentUndefined(Undefined):
    def __str__(self):
        return ""
    def __iter__(self):
        return iter([])


_jinja = Environment(
    loader=FileSystemLoader("."),
    autoescape=False,
    undefined=_SilentUndefined,
)


async def format_content(
    raw_text: str,
    classification: ClassificationResult,
    profile: Profile,
    user_id: str,
) -> tuple[str, dict]:
    """
    Returns (formatted_markdown_body, frontmatter_dict).
    Does NOT write to disk.
    """
    file_type = profile.get_file_type(classification.content_type)
    note_mode = classification.note_mode

    if note_mode == "personal":
        body = raw_text
        frontmatter = _build_frontmatter(classification, raw_text[:80], user_id, model="none", tokens=0)
        return body, frontmatter

    # structured — ask Claude to extract structured fields
    template_path = file_type.template_path if file_type else "templates/universal_note.md"

    system_prompt = f"""Ты форматировщик контента для second brain.
{profile.formatter_hints}

Твоя задача: извлечь структурированные данные из текста и вернуть JSON.

Тип документа: {classification.content_type}
Воркспейс: {classification.workspace}
Фича: {classification.feature_slug or 'нет'}
Упомянутые люди: {', '.join(classification.people_mentioned) if classification.people_mentioned else 'нет'}
Ключевые решения: {'; '.join(classification.key_decisions) if classification.key_decisions else 'нет'}

Верни JSON с полями для шаблона. Поля зависят от типа:
- title: заголовок документа
- date: дата (YYYY-MM-DD, сегодня если не указана)
- narrative: основной текст / краткое изложение
- people: список имён
- key_decisions: список решений
- action_items: список объектов {{task, owner, deadline}}
- workspace: воркспейс
- feature_slug: slug фичи
- agreements_section: текст договорённостей (для meeting)
- conditions: список условий (для agreement)
- deadline: дедлайн строкой
- status: статус документа
- Любые другие поля которые уместны для типа {classification.content_type}

Если данных нет — используй null или пустой список."""

    today = datetime.utcnow().strftime("%Y-%m-%d")
    is_large = len(raw_text) > settings.FORMATTER_INPUT_LIMIT
    format_input = raw_text[:settings.FORMATTER_INPUT_LIMIT]

    response_text, cost = await call_claude(
        system=system_prompt,
        user_message=format_input,
        user_id=user_id,
        operation="format",
        json_mode=True,
        model=settings.FAST_MODEL,
        max_tokens=4096,
    )

    try:
        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```", 2)[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.rsplit("```", 1)[0].strip()
        fields = json.loads(cleaned)
        parse_ok = True
    except json.JSONDecodeError:
        fields = {}
        parse_ok = False

    if not parse_ok:
        template_path = "templates/universal_note.md"

    fields.setdefault("date", today)
    fields.setdefault("title", classification.raw_title or "Заметка")
    fields.setdefault("workspace", classification.workspace)
    fields.setdefault("feature_slug", classification.feature_slug)
    fields.setdefault("narrative", raw_text if not is_large else format_input)
    fields.setdefault("people", classification.people_mentioned)
    fields.setdefault("key_decisions", classification.key_decisions)
    fields.setdefault("action_items", [])

    body = _render_template(template_path, fields)

    # Append full source text when doc was truncated for extraction
    if is_large:
        body += f"\n\n---\n\n## Исходный текст\n\n{raw_text}"

    tokens_used = len(response_text) // 4
    frontmatter = _build_frontmatter(classification, fields.get("title", ""), user_id, model=settings.FAST_MODEL, tokens=tokens_used)

    # Inject [[wikilinks]] so Obsidian graph shows connections
    storage = BrainStorage(user_id)
    frontmatter_with_path = {**frontmatter, "target_path": classification.target_path}
    body = await link_and_inject(body, frontmatter_with_path, storage, user_id)

    return body, frontmatter


def _render_template(template_path: str, fields: dict) -> str:
    try:
        template = _jinja.get_template(template_path)
        return template.render(**fields)
    except TemplateNotFound:
        return fields.get("narrative", "") or str(fields)
    except Exception:
        return fields.get("narrative", "") or str(fields)


def _build_frontmatter(
    classification: ClassificationResult,
    title: str,
    user_id: str,
    model: str,
    tokens: int,
) -> dict:
    now = datetime.utcnow().isoformat()
    return {
        "id": str(uuid.uuid4()),
        "type": classification.content_type,
        "note_mode": classification.note_mode,
        "status": "active",
        "domain": "work" if classification.workspace != "personal" else "personal",
        "workspace": classification.workspace,
        "feature_slug": classification.feature_slug or "",
        "tags": classification.suggested_tags,
        "date_created": now,
        "date_updated": now,
        "people": classification.people_mentioned,
        "source": "telegram",
        "linked_to": [],
        "ingest_cost_tokens": tokens,
        "ingest_model": model,
    }
