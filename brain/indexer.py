import json
from datetime import datetime
from pathlib import Path

from brain.storage import BrainStorage


def update_index(storage: BrainStorage, relative_path: str, frontmatter: dict, content: str):
    """Update manifest.json after writing a file."""
    manifest_path = storage.root / "_index" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    file_path = storage.root / relative_path
    size_bytes = file_path.stat().st_size if file_path.exists() else 0

    entry = {
        "id": frontmatter.get("id", ""),
        "path": relative_path,
        "type": frontmatter.get("type", "note"),
        "note_mode": frontmatter.get("note_mode", "structured"),
        "workspace": frontmatter.get("workspace", ""),
        "feature_slug": frontmatter.get("feature_slug", ""),
        "tags": frontmatter.get("tags", []),
        "people": frontmatter.get("people", []),
        "date_updated": frontmatter.get("date_updated", datetime.utcnow().isoformat()),
        "summary": content[:200].replace("\n", " "),
        "size_bytes": size_bytes,
    }

    # Replace existing entry or append
    existing = next((i for i, f in enumerate(manifest["files"]) if f["path"] == relative_path), None)
    if existing is not None:
        manifest["files"][existing] = entry
    else:
        manifest["files"].append(entry)

    manifest["last_updated"] = datetime.utcnow().isoformat()
    manifest["stats"] = _recalculate_stats(manifest["files"])

    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))


def remove_from_index(storage: BrainStorage, relative_path: str):
    manifest_path = storage.root / "_index" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"] = [f for f in manifest["files"] if f["path"] != relative_path]
    manifest["stats"] = _recalculate_stats(manifest["files"])
    manifest["last_updated"] = datetime.utcnow().isoformat()
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))


def get_manifest(storage: BrainStorage) -> dict:
    manifest_path = storage.root / "_index" / "manifest.json"
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def update_brain_summary(storage: BrainStorage):
    """
    Write a compact _index/_brain_summary.md used by classifier as context.
    Much cheaper than passing full manifest (~50KB) in prompts.
    """
    manifest_path = storage.root / "_index" / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return

    files = manifest.get("files", [])
    stats = manifest.get("stats", {})

    # Last 10 entries (most recent first)
    recent = sorted(files, key=lambda f: f.get("date_updated", ""), reverse=True)[:10]

    # Active feature slugs
    feature_slugs = sorted({
        f["feature_slug"] for f in files
        if f.get("feature_slug") and f.get("type") in ("feature", "decision", "meeting")
    })

    by_type = stats.get("by_type", {})
    by_ws = stats.get("by_workspace", {})

    lines = [
        f"# Brain Summary (авто-обновляется)",
        f"Обновлено: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC",
        "",
        "## Статистика",
        f"{stats.get('total_files', 0)} записей | " +
        " | ".join(f"{t}: {c}" for t, c in sorted(by_type.items(), key=lambda x: -x[1])[:5]),
        "",
        "## Воркспейсы",
    ] + [f"- {w}: {c} записей" for w, c in sorted(by_ws.items(), key=lambda x: -x[1])]

    if feature_slugs:
        lines += ["", "## Активные фичи"] + [f"- {s}" for s in feature_slugs[:10]]

    lines += ["", "## Последние 10 записей"]
    for f in recent:
        date = f.get("date_updated", "")[:10]
        lines.append(f"- [{f.get('type', '?')}] {date}: {f.get('summary', '')[:80]}")

    summary_path = storage.root / "_index" / "_brain_summary.md"
    summary_path.write_text("\n".join(lines), encoding="utf-8")


def _recalculate_stats(files: list[dict]) -> dict:
    by_type: dict[str, int] = {}
    by_workspace: dict[str, int] = {}
    for f in files:
        t = f.get("type", "unknown")
        w = f.get("workspace", "unknown")
        by_type[t] = by_type.get(t, 0) + 1
        by_workspace[w] = by_workspace.get(w, 0) + 1
    return {
        "total_files": len(files),
        "by_type": by_type,
        "by_workspace": by_workspace,
    }
