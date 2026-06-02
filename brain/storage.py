import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from config.settings import settings


class PathTraversalError(Exception):
    pass


class BrainStorage:
    """Isolated brain storage for one user. All paths are validated against root."""

    def __init__(self, user_id: str):
        if not re.match(r'^[a-zA-Z0-9_\-]{1,64}$', str(user_id)):
            raise ValueError(f"Invalid user_id format: {user_id}")
        self.user_id = str(user_id)
        self.root = (settings.DATA_PATH / "users" / self.user_id / "brain").resolve()
        self.chroma_path = (settings.DATA_PATH / "users" / self.user_id / "chroma").resolve()
        self.meta_path = (settings.DATA_PATH / "users" / self.user_id / "meta.json").resolve()
        self._ensure_initialized()

    def _ensure_initialized(self):
        dirs = [
            self.root / "_inbox",
            self.root / "_index",
            self.root / "personal" / "health",
            self.root / "personal" / "travel",
            self.root / "personal" / "interests",
            self.root / "work",
            self.chroma_path,
            self.meta_path.parent,
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

        if not self.meta_path.exists():
            self.meta_path.write_text(json.dumps({
                "user_id": self.user_id,
                "profile_id": "universal",
                "active_workspace": "work",
                "tariff": "free",
                "trial_ends_at": None,
                "subscription_active": False,
                "total_tokens_used": 0,
                "total_cost_usd": 0.0,
                "created_at": datetime.utcnow().isoformat(),
            }, indent=2, ensure_ascii=False))

        index_path = self.root / "_index" / "manifest.json"
        if not index_path.exists():
            index_path.write_text(json.dumps({
                "version": 2,
                "last_updated": datetime.utcnow().isoformat(),
                "user_id": self.user_id,
                "files": [],
                "stats": {
                    "total_files": 0,
                    "by_type": {},
                    "by_workspace": {},
                },
            }, indent=2, ensure_ascii=False))

    def _safe_path(self, relative_path: str) -> Path:
        """Resolve path and verify it stays within root."""
        resolved = (self.root / relative_path).resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError:
            raise PathTraversalError(
                f"Path '{relative_path}' escapes storage root for user '{self.user_id}'"
            )
        return resolved

    def write_file(self, relative_path: str, content: str, frontmatter: dict) -> str:
        path = self._safe_path(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        fm_lines = ["---"]
        for k, v in frontmatter.items():
            safe_v = self._sanitize_frontmatter_value(v)
            fm_lines.append(f"{k}: {safe_v}")
        fm_lines.append("---")
        fm_lines.append("")

        full_content = "\n".join(fm_lines) + content
        path.write_text(full_content, encoding="utf-8")
        return str(path)

    def read_file(self, relative_path: str) -> tuple[dict, str]:
        path = self._safe_path(relative_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {relative_path}")

        raw = path.read_text(encoding="utf-8")
        return self._parse_frontmatter(raw)

    def append_to_file(self, relative_path: str, content_block: str):
        path = self._safe_path(relative_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {relative_path}")
        with path.open("a", encoding="utf-8") as f:
            f.write("\n\n" + content_block)

    def list_files(self, glob_pattern: str = "**/*.md") -> list[Path]:
        return list(self.root.glob(glob_pattern))

    def file_exists(self, relative_path: str) -> bool:
        try:
            path = self._safe_path(relative_path)
            return path.exists()
        except PathTraversalError:
            return False

    def get_meta(self) -> dict:
        return json.loads(self.meta_path.read_text(encoding="utf-8"))

    def update_meta(self, updates: dict):
        meta = self.get_meta()
        meta.update(updates)
        self.meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))

    def get_inbox_files(self) -> list[Path]:
        return list((self.root / "_inbox").glob("*.md"))

    def move_from_inbox(self, filename: str, target_relative_path: str) -> str:
        src = self._safe_path(f"_inbox/{filename}")
        dst = self._safe_path(target_relative_path)
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        return str(dst)

    RECORD_TYPES = ("record_decision", "record_agreement", "record_fact", "record_principle")

    def append_to_record(self, record_type: str, content: str, title: str = ""):
        """
        Append-only write to records/ files. Records are immutable history —
        nothing is ever overwritten, only appended.
        """
        type_map = {
            "record_decision": "decisions.md",
            "record_agreement": "agreements.md",
            "record_fact": "facts.md",
            "record_principle": "principles.md",
        }
        filename = type_map.get(record_type, "notes.md")
        record_path = self.root / "records" / filename
        record_path.parent.mkdir(parents=True, exist_ok=True)

        # Init file with header if new
        if not record_path.exists():
            record_path.write_text(
                f"# {filename.replace('.md', '').capitalize()}\n\n"
                f"*Append-only. Записи не удаляются и не редактируются.*\n\n",
                encoding="utf-8",
            )

        from datetime import datetime
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
        heading = f"### {title}" if title else f"### {timestamp}"
        entry = f"\n---\n{heading}\n*{timestamp} UTC*\n\n{content.strip()}\n"
        with record_path.open("a", encoding="utf-8") as f:
            f.write(entry)

    @staticmethod
    def _sanitize_frontmatter_value(value) -> str:
        if isinstance(value, (list, dict)):
            return json.dumps(value, ensure_ascii=False)
        s = str(value)
        # Escape characters that could break YAML frontmatter
        if any(c in s for c in [':', '#', '[', ']', '{', '}', '|', '>', '!', '%', '@', '`', '\n']):
            escaped = s.replace('"', '\\"')
            return f'"{escaped}"'
        return s

    @staticmethod
    def _parse_frontmatter(raw: str) -> tuple[dict, str]:
        if not raw.startswith("---"):
            return {}, raw

        end = raw.find("---", 3)
        if end == -1:
            return {}, raw

        fm_block = raw[3:end].strip()
        content = raw[end + 3:].lstrip("\n")

        frontmatter = {}
        for line in fm_block.splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                frontmatter[k.strip()] = v.strip()

        return frontmatter, content
