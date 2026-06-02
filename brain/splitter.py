"""
Content splitter: detects if incoming text contains multiple distinct
topics/types and splits it into chunks, each going to a separate note.

Example: a long message with meeting notes + decisions + tasks
→ [meeting chunk, decisions chunk, tasks chunk]
"""
import json
from dataclasses import dataclass, field
from typing import Optional

from core.claude import call_claude


@dataclass
class ContentChunk:
    title: str
    content: str
    chunk_type: str          # meeting | decision | task | research | note | etc.
    hint: str = ""           # hint for classifier


@dataclass
class SplitResult:
    should_split: bool
    chunks: list[ContentChunk] = field(default_factory=list)
    reason: str = ""


# Minimum chars to even bother checking for splits
MIN_LENGTH_TO_SPLIT = 300


async def analyze_and_split(raw_text: str, user_id: str) -> SplitResult:
    """
    Check if content should be split into multiple notes.
    Short texts go as-is. Long texts get analyzed by Claude.
    """
    if len(raw_text) < MIN_LENGTH_TO_SPLIT:
        return SplitResult(should_split=False, reason="Текст слишком короткий для разбивки.")

    system = """Ты анализатор контента для second brain.

Твоя задача: определить, содержит ли текст несколько ПРИНЦИПИАЛЬНО разных смысловых блоков,
которые лучше хранить в отдельных заметках.

Признаки что нужна разбивка:
- Есть конспект встречи И отдельный список задач → 2 заметки
- Есть исследование/статья И решение по нему → 2 заметки
- Есть несколько несвязанных тем → несколько заметок

Признаки что НЕ нужна разбивка:
- Единая тема, просто длинный текст
- Встреча с action items (action items часть встречи)
- Статья с выводами (единый документ)

Верни JSON:
{
  "should_split": true/false,
  "reason": "краткое объяснение решения",
  "chunks": [
    {
      "title": "Заголовок этой части",
      "content": "Текст этой части (скопируй релевантный фрагмент)",
      "chunk_type": "meeting|decision|task|research|note|feature|agreement",
      "hint": "подсказка для классификатора на русском"
    }
  ]
}

Если should_split=false — chunks должен быть пустым массивом [].
Максимум 4 чанка."""

    try:
        response, _ = await call_claude(
            system=system,
            user_message=raw_text[:4000],
            user_id=user_id,
            operation="ingest",
            json_mode=True,
        )

        cleaned = response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```", 2)[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.rsplit("```", 1)[0].strip()

        data = json.loads(cleaned)

        if not data.get("should_split") or not data.get("chunks"):
            return SplitResult(should_split=False, reason=data.get("reason", ""))

        chunks = [
            ContentChunk(
                title=c.get("title", "Без названия"),
                content=c.get("content", ""),
                chunk_type=c.get("chunk_type", "note"),
                hint=c.get("hint", ""),
            )
            for c in data["chunks"]
            if c.get("content", "").strip()
        ]

        if len(chunks) <= 1:
            return SplitResult(should_split=False, reason="Только один смысловой блок.")

        return SplitResult(
            should_split=True,
            chunks=chunks,
            reason=data.get("reason", ""),
        )

    except Exception:
        return SplitResult(should_split=False, reason="Ошибка анализа — сохраняю целиком.")
