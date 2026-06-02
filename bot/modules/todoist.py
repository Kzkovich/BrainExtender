"""
Todoist module: detects tasks in content and creates them in Todoist.
"""
import json
from typing import Optional

from bot.modules.base import BrainModule, ModuleResult
from config.settings import settings
from core.claude import call_claude


class TodoistModule(BrainModule):
    module_id = "todoist"
    button_label = "✅ Создать задачи в Todoist"

    def can_handle(self, content: str, classification_type: str) -> bool:
        if not settings.TODOIST_API_KEY:
            return False
        # Applicable for any content that might have action items
        task_keywords = [
            "нужно", "сделать", "задача", "дедлайн", "deadline",
            "к ", "до ", "ответственный", "action", "todo", "[ ]",
            "поставить", "назначить", "проверить", "отправить",
        ]
        content_lower = content.lower()
        return any(kw in content_lower for kw in task_keywords)

    async def run(self, content: str, user_id: str, extra: dict) -> ModuleResult:
        # Step 1: Extract tasks from content via Claude
        tasks = await self._extract_tasks(content, user_id)
        if not tasks:
            return ModuleResult(success=False, message="Задач не найдено в тексте.")

        # Step 2: Create tasks in Todoist
        created = []
        failed = []
        for task in tasks:
            ok = await self._create_todoist_task(task)
            if ok:
                created.append(task["content"])
            else:
                failed.append(task["content"])

        if not created:
            return ModuleResult(
                success=False,
                message=f"Не удалось создать задачи в Todoist. Проверь API ключ.",
            )

        lines = [f"✅ *Создано в Todoist ({len(created)}):*"]
        for t in created:
            lines.append(f"• {t}")
        if failed:
            lines.append(f"\n⚠️ Не удалось: {len(failed)}")

        return ModuleResult(success=True, message="\n".join(lines), data={"created": created})

    async def _extract_tasks(self, content: str, user_id: str) -> list[dict]:
        """Ask Claude to extract actionable tasks from content."""
        system = """Извлеки все конкретные задачи/action items из текста.
Задача — это конкретное действие с исполнителем или без, которое нужно выполнить.

Верни JSON массив:
[
  {
    "content": "Краткое название задачи (1 строка)",
    "description": "Детали если есть",
    "due_string": "tomorrow|next week|2026-06-10 или null",
    "priority": 1-4
  }
]
priority: 1=срочно, 2=высокий, 3=средний, 4=обычный
Если задач нет — верни []."""

        try:
            response, _ = await call_claude(
                system=system,
                user_message=content[:3000],
                user_id=user_id,
                operation="query",
                json_mode=True,
            )
            cleaned = response.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("```", 2)[1]
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:]
                cleaned = cleaned.rsplit("```", 1)[0].strip()
            tasks = json.loads(cleaned)
            return tasks if isinstance(tasks, list) else []
        except Exception:
            return []

    async def _create_todoist_task(self, task: dict) -> bool:
        """Create a single task in Todoist via REST API."""
        try:
            import httpx
            payload = {
                "content": task.get("content", "Задача"),
                "priority": task.get("priority", 4),
            }
            if task.get("description"):
                payload["description"] = task["description"]
            if task.get("due_string") and task["due_string"] != "null":
                payload["due_string"] = task["due_string"]
                payload["due_lang"] = "ru"

            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(
                    "https://api.todoist.com/rest/v2/tasks",
                    headers={"Authorization": f"Bearer {settings.TODOIST_API_KEY}"},
                    json=payload,
                )
            return r.status_code == 200
        except Exception:
            return False
