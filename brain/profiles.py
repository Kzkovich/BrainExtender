import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

PROFILES_DIR = Path("profiles")


@dataclass
class FileTypeConfig:
    id: str
    name: str
    template_path: str
    note_mode: str = "structured"
    append_target: Optional[str] = None
    create_in_todoist: bool = False


@dataclass
class WorkspaceConfig:
    slug: str
    name: str
    domain: str


@dataclass
class Profile:
    profile_id: str
    display_name: str
    description: str
    file_types: list[FileTypeConfig]
    default_workspaces: list[WorkspaceConfig]
    classifier_hints: str = ""
    formatter_hints: str = ""
    domain_vocabulary: dict = field(default_factory=dict)

    def get_file_type(self, type_id: str) -> Optional[FileTypeConfig]:
        return next((ft for ft in self.file_types if ft.id == type_id), None)

    def file_type_ids(self) -> list[str]:
        return [ft.id for ft in self.file_types]


@dataclass
class ProfileMeta:
    profile_id: str
    display_name: str
    description: str


class ProfileLoader:
    @staticmethod
    def load(profile_id: str) -> Profile:
        path = PROFILES_DIR / f"{profile_id}.yaml"
        if not path.exists():
            path = PROFILES_DIR / "universal.yaml"
        return ProfileLoader._parse(path)

    @staticmethod
    def list_available() -> list[ProfileMeta]:
        metas = []
        for p in sorted(PROFILES_DIR.glob("*.yaml")):
            if p.stem == "custom_template":
                continue
            raw = yaml.safe_load(p.read_text(encoding="utf-8"))
            metas.append(ProfileMeta(
                profile_id=raw["profile_id"],
                display_name=raw["display_name"],
                description=raw["description"],
            ))
        return metas

    @staticmethod
    def create_custom(user_id: str, base: str = "universal") -> Profile:
        from config.settings import settings
        src = PROFILES_DIR / f"{base}.yaml"
        if not src.exists():
            src = PROFILES_DIR / "universal.yaml"
        dst = settings.DATA_PATH / "users" / user_id / "custom_profile.yaml"
        shutil.copy(src, dst)
        return ProfileLoader._parse(dst)

    @staticmethod
    def _parse(path: Path) -> Profile:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))

        file_types = [
            FileTypeConfig(
                id=ft["id"],
                name=ft["name"],
                template_path=ft["template_path"],
                note_mode=ft.get("note_mode", "structured"),
                append_target=ft.get("append_target"),
                create_in_todoist=ft.get("create_in_todoist", False),
            )
            for ft in raw.get("file_types", [])
        ]

        workspaces = [
            WorkspaceConfig(slug=w["slug"], name=w["name"], domain=w["domain"])
            for w in raw.get("default_workspaces", [])
        ]

        return Profile(
            profile_id=raw["profile_id"],
            display_name=raw["display_name"],
            description=raw["description"],
            file_types=file_types,
            default_workspaces=workspaces,
            classifier_hints=raw.get("classifier_hints", ""),
            formatter_hints=raw.get("formatter_hints", ""),
            domain_vocabulary=raw.get("domain_vocabulary", {}),
        )
