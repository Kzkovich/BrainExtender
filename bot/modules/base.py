from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class ModuleResult:
    success: bool
    message: str
    data: Optional[dict] = None


class BrainModule(ABC):
    """Base class for all post-save modules."""

    @property
    @abstractmethod
    def module_id(self) -> str:
        """Unique ID used in callback_data."""

    @property
    @abstractmethod
    def button_label(self) -> str:
        """Text shown on inline button."""

    @abstractmethod
    def can_handle(self, content: str, classification_type: str) -> bool:
        """Return True if module is applicable for this content."""

    @abstractmethod
    async def run(self, content: str, user_id: str, extra: dict) -> ModuleResult:
        """Execute the module action."""
