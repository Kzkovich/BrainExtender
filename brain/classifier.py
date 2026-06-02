import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from brain.profiles import ProfileLoader
from brain.storage import BrainStorage
from config.settings import settings
from core.claude import call_claude


@dataclass
class ClassificationResult:
    content_type: str
    workspace: str
    feature_slug: Optional[str]
    action: str                          # create_file | update_file | append_to_file | skip
    target_path: str
    note_mode: str                       # structured | personal
    suggested_tags: list[str] = field(default_factory=list)
    people_mentioned: list[str] = field(default_factory=list)
    key_decisions: list[str] = field(default_factory=list)
    delta_summary: str = ""
    novelty_percent: int = 100
    confidence: float = 0.9
    raw_title: str = ""
    task_probability: float = 0.0
    suggested_tasks: list[str] = field(default_factory=list)
    should_split: bool = False
    split_chunks: list[dict] = field(default_factory=list)  # [{title, content, chunk_type, hint}]


def _build_context_summary(storage: BrainStorage) -> str:
    """Use compact _brain_summary.md if available (faster, cheaper). Fallback to manifest."""
    summary_path = storage.root / "_index" / "_brain_summary.md"
    if summary_path.exists():
        try:
            return summary_path.read_text(encoding="utf-8")
        except Exception:
            pass
    # Fallback: build from manifest
    try:
        manifest_path = storage.root / "_index" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        files = manifest.get("files", [])[-15:]
        if not files:
            return "Brain пуст — это первые записи."
        stats = manifest.get("stats", {})
        lines = [f"- [{f['type']}] {f.get('summary', '')[:60]}" for f in files]
        return (
            f"Записей в brain: {stats.get('total_files', 0)}\n"
            f"Последние:\n" + "\n".join(lines)
        )
    except Exception:
        return "Brain пуст."


def _read_workspace_context(storage: BrainStorage, workspace: str) -> str:
    """Read _context/ files from active workspace to give classifier domain knowledge."""
    context_parts = []

    # Search in both work/{workspace}/_context/ and work/_context/
    search_paths = [
        storage.root / "work" / workspace / "_context",
        storage.root / "work" / "_context",
    ]

    for ctx_dir in search_paths:
        if not ctx_dir.exists():
            continue
        for md_file in sorted(ctx_dir.glob("*.md")):
            try:
                text = md_file.read_text(encoding="utf-8")
                # Strip frontmatter
                if text.startswith("---"):
                    end = text.find("---", 3)
                    if end != -1:
                        text = text[end + 3:].lstrip("\n")
                context_parts.append(f"### {md_file.stem}\n{text.strip()}")
            except Exception:
                pass

    if not context_parts:
        return ""

    return "## Контекст воркспейса (помогает классифицировать):\n\n" + "\n\n".join(context_parts)


async def classify(raw_text: str, user_id: str) -> ClassificationResult:
    storage = BrainStorage(user_id)
    meta = storage.get_meta()
    profile = ProfileLoader.load(meta.get("profile_id", "universal"))
    brain_context = _build_context_summary(storage)
    active_workspace = meta.get("active_workspace", "work")
    workspace_context = _read_workspace_context(storage, active_workspace)

    file_types_desc = "\n".join(
        f'  - "{ft.id}": {ft.name}'
        for ft in profile.file_types
    )

    system_prompt = f"""Ты классификатор контента для персонального second brain.
Профиль пользователя: {profile.display_name}

{profile.classifier_hints}

Доступные типы файлов:
{file_types_desc}

Текущее состояние brain:
{brain_context}

{workspace_context}

Активный воркспейс: {active_workspace}

Твоя задача: проанализировать входящий текст и вернуть JSON с классификацией.

JSON-схема ответа:
{{
  "content_type": "<один из типов из списка выше>",
  "workspace": "<slug воркспейса>",
  "feature_slug": "<slug фичи или null>",
  "action": "<create_file|update_file|append_to_file|skip>",
  "target_path": "<относительный путь от brain/, например work/alfa-bank/meetings/2024-01-15-vitrina.md>",
  "note_mode": "<structured|personal>",
  "suggested_tags": ["тег1", "тег2"],
  "people_mentioned": ["Имя1", "Имя2"],
  "key_decisions": ["решение1", "решение2"],
  "delta_summary": "<краткое описание что именно нового в этом тексте>",
  "novelty_percent": <0-100>,
  "confidence": <0.0-1.0>,
  "raw_title": "<предлагаемый заголовок файла>",
  "task_probability": <0.0-1.0, вероятность что нужно поставить задачу>,
  "suggested_tasks": ["Готовая формулировка задачи 1", "Задача 2"],
  "should_split": <true если текст содержит ПРИНЦИПИАЛЬНО разные темы для отдельных заметок>,
  "split_chunks": []
}}

Правила для task_probability:
- 0.9+ : явная задача/дедлайн/поручение ("нужно сделать X до пятницы")
- 0.7–0.9 : есть action items, но неявные ("решили что Кирилл проверит")
- 0.4–0.7 : возможно нужна задача
- < 0.4 : задача не нужна (статья, исследование, личная заметка)
suggested_tasks — конкретные глагольные формулировки, не более 3, пустой массив если task_probability < 0.4

Правила для should_split / split_chunks:
- should_split=true ТОЛЬКО если в тексте несколько ПРИНЦИПИАЛЬНО разных тем (встреча + отдельное исследование)
- should_split=false если единая тема, пусть и длинная (встреча с action items — это одна заметка)
- Если should_split=true, заполни split_chunks:
  [{"title": "...", "content": "фрагмент текста", "chunk_type": "meeting|research|decision|note", "hint": "подсказка"}]
- Максимум 4 чанка. Если doubt — ставь should_split=false

Правила для target_path:
- Встречи: work/{{workspace}}/meetings/{{YYYY-MM-DD}}-{{slug}}.md
- Фичи: work/{{workspace}}/features/{{feature_slug}}/overview.md
- Решения: work/{{workspace}}/features/{{feature_slug}}/decisions.md
- Исследования: work/{{workspace}}/research/{{slug}}.md
- Задачи: work/{{workspace}}/tasks/{{slug}}.md
- Личные заметки: personal/interests/{{slug}}.md
- note_mode=personal → всегда в personal/"""

    classify_input = raw_text[:settings.CLASSIFIER_INPUT_LIMIT]

    response_text, _ = await call_claude(
        system=system_prompt,
        user_message=classify_input,
        user_id=user_id,
        operation="ingest",
        json_mode=True,
        model=settings.FAST_MODEL,  # Routing task — Haiku достаточно
    )

    try:
        cleaned = response_text.strip()
        # Strip markdown code fences if Claude wraps response in ```json ... ```
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```", 2)[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.rsplit("```", 1)[0].strip()
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Fallback: save as note
        data = {
            "content_type": "note",
            "workspace": active_workspace,
            "feature_slug": None,
            "action": "create_file",
            "target_path": f"personal/interests/{datetime.utcnow().strftime('%Y-%m-%d')}-note.md",
            "note_mode": "personal",
            "suggested_tags": [],
            "people_mentioned": [],
            "key_decisions": [],
            "delta_summary": "Не удалось классифицировать, сохранено как заметка",
            "novelty_percent": 100,
            "confidence": 0.3,
            "raw_title": "Заметка",
            "task_probability": 0.0,
            "suggested_tasks": [],
            "should_split": False,
            "split_chunks": [],
        }

    return ClassificationResult(**{k: data.get(k, v) for k, v in {
        "content_type": "note",
        "workspace": active_workspace,
        "feature_slug": None,
        "action": "create_file",
        "target_path": f"personal/interests/{datetime.utcnow().strftime('%Y-%m-%d')}-note.md",
        "note_mode": "structured",
        "suggested_tags": [],
        "people_mentioned": [],
        "key_decisions": [],
        "delta_summary": "",
        "novelty_percent": 100,
        "confidence": 0.9,
        "raw_title": "Заметка",
        "task_probability": 0.0,
        "suggested_tasks": [],
        "should_split": False,
        "split_chunks": [],
    }.items()})
