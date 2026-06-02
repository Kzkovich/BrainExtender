from bot.modules.base import BrainModule, ModuleResult
from bot.modules.todoist import TodoistModule

# Registry — add new modules here
ALL_MODULES: list[BrainModule] = [
    TodoistModule(),
]


def get_applicable_modules(content: str, classification_type: str) -> list[BrainModule]:
    """Return modules that can handle this content."""
    return [m for m in ALL_MODULES if m.can_handle(content, classification_type)]
