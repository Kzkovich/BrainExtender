"""
Find semantically related notes and inject [[wikilinks]] into note body.
Obsidian graph view only shows links written as [[...]] in the document body.
"""
import json
import re
from pathlib import Path

from brain.storage import BrainStorage


def _get_candidate_notes(storage: BrainStorage, exclude_path: str = "") -> list[dict]:
    """Return list of {stem, path, summary, type} for all indexed notes."""
    manifest_path = storage.root / "_index" / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    candidates = []
    for f in manifest.get("files", []):
        if f["path"] == exclude_path:
            continue
        stem = Path(f["path"]).stem
        candidates.append({
            "stem": stem,
            "path": f["path"],
            "summary": f.get("summary", ""),
            "type": f.get("type", ""),
            "workspace": f.get("workspace", ""),
            "tags": f.get("tags", []),
            "people": f.get("people", []),
        })
    return candidates


async def find_related(
    content: str,
    frontmatter: dict,
    storage: BrainStorage,
    user_id: str,
    max_links: int = 5,
) -> list[dict]:
    """
    Ask Claude to pick which candidate notes are related to this content.
    Returns list of {stem, path, reason}.
    """
    candidates = _get_candidate_notes(storage, exclude_path=frontmatter.get("target_path", ""))
    if not candidates:
        return []

    from config.settings import settings
    from core.claude import call_claude

    candidates_text = "\n".join(
        f'- stem="{c["stem"]}" type={c["type"]} ws={c["workspace"]} | {c["summary"][:100]}'
        for c in candidates
    )

    system = (
        "Ты помощник который находит связи между заметками в личном second brain.\n"
        "Твоя задача: из списка кандидатов выбрать те, которые семантически связаны с данным текстом.\n"
        "Связь — общая тема, упомянутые люди, продолжение мысли, решение из той же области.\n\n"
        f"Кандидаты:\n{candidates_text}\n\n"
        f"Верни JSON массив (максимум {max_links} элементов):\n"
        '[{"stem": "имя-файла", "reason": "почему связаны"}]\n'
        "Если связей нет — верни пустой массив [].\n"
        "Отвечай ТОЛЬКО JSON без лишнего текста."
    )

    note_text = f"Тип: {frontmatter.get('type', '')}\nТеги: {frontmatter.get('tags', [])}\n\n{content[:800]}"

    try:
        response, _ = await call_claude(
            system=system,
            user_message=note_text,
            user_id=user_id,
            operation="link",
            json_mode=True,
            model=settings.FAST_MODEL,
        )
        cleaned = response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```", 2)[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.rsplit("```", 1)[0].strip()
        related = json.loads(cleaned)
        if not isinstance(related, list):
            return []
        # Validate stems exist in candidates
        valid_stems = {c["stem"] for c in candidates}
        return [r for r in related if isinstance(r, dict) and r.get("stem") in valid_stems]
    except Exception:
        return []


def inject_links(body: str, related: list[dict]) -> str:
    """Append a '## Связанные заметки' section with [[wikilinks]] to note body."""
    if not related:
        return body

    # Remove existing links section if present
    body = re.sub(r"\n## Связанные заметки\n[\s\S]*$", "", body).rstrip()

    lines = ["\n\n## Связанные заметки\n"]
    for r in related:
        stem = r["stem"]
        reason = r.get("reason", "")
        lines.append(f"- [[{stem}]] — {reason}")

    return body + "\n".join(lines)


def extract_wikilinks(body: str) -> list[str]:
    """Extract all [[link]] references from a note body."""
    return re.findall(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]", body)


async def link_and_inject(
    body: str,
    frontmatter: dict,
    storage: BrainStorage,
    user_id: str,
) -> str:
    """Full pipeline: find related notes → inject [[links]] → return updated body."""
    related = await find_related(body, frontmatter, storage, user_id)
    return inject_links(body, related)
