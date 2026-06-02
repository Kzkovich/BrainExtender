"""
Todoist module: uses task_probability from classifier to decide
whether to suggest task creation. Tasks are pre-formulated by classifier.
"""
from bot.modules.base import BrainModule, ModuleResult
from config.settings import settings

TASK_THRESHOLD = 0.45   # minimum probability to show the button


class TodoistModule(BrainModule):
    module_id = "todoist"

    @property
    def button_label(self) -> str:
        return "✅ Создать задачи в Todoist"

    def can_handle(self, content: str, classification_type: str) -> bool:
        # This is the fallback — real check uses classification object
        return bool(settings.TODOIST_API_KEY)

    def can_handle_with_classification(self, classification) -> tuple[bool, str]:
        """
        Main check — uses pre-computed task_probability from classifier.
        Returns (should_show, button_label_with_probability).
        """
        if not settings.TODOIST_API_KEY:
            return False, ""

        prob = getattr(classification, "task_probability", 0.0)
        tasks = getattr(classification, "suggested_tasks", [])

        if prob < TASK_THRESHOLD:
            return False, ""

        # Format probability label
        if prob >= 0.85:
            prob_label = "уверен"
        elif prob >= 0.65:
            prob_label = f"{int(prob * 100)}% вероятно"
        else:
            prob_label = f"{int(prob * 100)}%?"

        # Show first task preview in button if available
        if tasks:
            first_task = tasks[0][:40] + ("…" if len(tasks[0]) > 40 else "")
            label = f"✅ «{first_task}» ({prob_label})"
        else:
            label = f"✅ Поставить задачу ({prob_label})"

        return True, label

    async def run(self, content: str, user_id: str, extra: dict) -> ModuleResult:
        classification = extra.get("classification")
        tasks = getattr(classification, "suggested_tasks", []) if classification else []

        # If classifier gave us tasks — use them directly (no extra Claude call)
        if not tasks:
            return ModuleResult(
                success=False,
                message="🌊 Задачи не обнаружены в этом тексте.",
            )

        created = []
        failed = []
        for task_text in tasks:
            ok = await self._create_todoist_task(task_text)
            if ok:
                created.append(task_text)
            else:
                failed.append(task_text)

        if not created:
            return ModuleResult(
                success=False,
                message="🌊 Не удалось создать задачи в Todoist.\nПроверь TODOIST_API_KEY на сервере.",
            )

        lines = [f"⚓ *Задачи причалили в Todoist ({len(created)}):*\n"]
        for t in created:
            lines.append(f"• {t}")
        if failed:
            lines.append(f"\n⚠️ Не удалось создать: {len(failed)}")

        return ModuleResult(success=True, message="\n".join(lines), data={"created": created})

    async def _create_todoist_task(self, task_text: str) -> bool:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(
                    "https://api.todoist.com/rest/v2/tasks",
                    headers={"Authorization": f"Bearer {settings.TODOIST_API_KEY}"},
                    json={"content": task_text, "priority": 3},
                )
            return r.status_code == 200
        except Exception:
            return False
