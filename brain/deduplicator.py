"""
Before saving new content, check if brain already has related notes.
Decide: create_new | update_existing | link_to_existing
"""
import json
from dataclasses import dataclass
from typing import Optional

from brain.classifier import ClassificationResult
from brain.indexer import get_manifest
from brain.storage import BrainStorage
from config.settings import settings
from core.claude import call_claude


@dataclass
class DeduplicationResult:
    action: str                        # create_new | update_existing | link_to_existing
    existing_path: Optional[str]       # path to existing note if found
    reason: str                        # explanation
    merge_hint: Optional[str] = None   # how to merge if updating


async def check_before_save(
    content: str,
    classification: ClassificationResult,
    storage: BrainStorage,
    user_id: str,
) -> DeduplicationResult:
    """
    Check brain for existing related notes.
    Returns decision on how to handle the new content.
    """
    manifest = get_manifest(storage)
    files = manifest.get("files", [])

    if not files:
        return DeduplicationResult(
            action="create_new",
            existing_path=None,
            reason="Brain пуст — первая запись.",
        )

    # Filter candidates by same type and workspace
    candidates = [
        f for f in files
        if f.get("workspace") == classification.workspace
        or f.get("type") == classification.content_type
    ][-15:]  # last 15 most relevant

    if not candidates:
        return DeduplicationResult(
            action="create_new",
            existing_path=None,
            reason="Нет похожих записей в этом воркспейсе.",
        )

    candidates_text = "\n".join(
        f'- path="{c["path"]}" type={c["type"]} | {c.get("summary", "")[:120]}'
        for c in candidates
    )

    system = f"""Ты помощник который решает как обработать новый контент для second brain.

Новый контент:
Тип: {classification.content_type}
Заголовок: {classification.raw_title}
Воркспейс: {classification.workspace}
Фича: {classification.feature_slug or 'нет'}

Существующие записи в brain:
{candidates_text}

Реши что делать с новым контентом:
1. "create_new" — создать новую запись (нет ничего похожего)
2. "update_existing" — обновить/дополнить существующую (та же тема, можно обогатить)
3. "link_to_existing" — создать новую, но добавить ссылку на существующую

Верни JSON:
{{
  "action": "create_new|update_existing|link_to_existing",
  "existing_path": "путь/к/файлу или null",
  "reason": "краткое объяснение",
  "merge_hint": "что именно добавить в существующую запись (если update_existing)"
}}

Отвечай ТОЛЬКО JSON."""

    try:
        response, _ = await call_claude(
            system=system,
            user_message=content[:600],
            user_id=user_id,
            operation="ingest",
            json_mode=True,
            model=settings.FAST_MODEL,
        )
        cleaned = response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```", 2)[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.rsplit("```", 1)[0].strip()

        data = json.loads(cleaned)
        return DeduplicationResult(
            action=data.get("action", "create_new"),
            existing_path=data.get("existing_path"),
            reason=data.get("reason", ""),
            merge_hint=data.get("merge_hint"),
        )
    except Exception:
        return DeduplicationResult(
            action="create_new",
            existing_path=None,
            reason="Ошибка проверки — создаю новую запись.",
        )


async def enrich_existing(
    existing_body: str,
    new_content: str,
    merge_hint: str,
    user_id: str,
) -> str:
    """Merge new content into existing note body.
    Large documents are appended as a dated section to avoid expensive rewrites."""
    from datetime import datetime

    # If combined content is too large, just append — no Claude call needed
    if len(existing_body) + len(new_content) > settings.ENRICH_APPEND_THRESHOLD:
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        return existing_body.rstrip() + f"\n\n---\n\n## Обновлено {date_str}\n\n{new_content}"

    system = """Ты редактор second brain. Тебе дана существующая запись и новый контент.
Обогати существующую запись новой информацией — добавь новые факты, обнови данные, дополни разделы.
Не удаляй существующий контент. Верни полное обновлённое тело заметки (без frontmatter)."""

    merged, _ = await call_claude(
        system=system,
        user_message=f"Существующая запись:\n{existing_body}\n\n---\nНовый контент:\n{new_content}\n\nЧто добавить: {merge_hint}",
        user_id=user_id,
        operation="format",
        model=settings.FAST_MODEL,
        max_tokens=8192,
    )
    return merged
