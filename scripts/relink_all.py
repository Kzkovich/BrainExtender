#!/usr/bin/env python3
"""
Retroactively add [[wikilinks]] to all existing notes in a user's brain.
Run once after adding notes, or whenever you want to refresh links.

Usage:
  python scripts/relink_all.py --user-id=390604543
  python scripts/relink_all.py --user-id=390604543 --dry-run
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from brain.indexer import get_manifest
from brain.linker import extract_wikilinks, find_related, inject_links
from brain.storage import BrainStorage


async def relink_user(user_id: str, dry_run: bool = False):
    storage = BrainStorage(user_id)
    manifest = get_manifest(storage)
    files = manifest.get("files", [])

    if not files:
        print(f"No files found for user {user_id}.")
        return

    print(f"Found {len(files)} notes. Processing...\n")
    updated = 0

    for entry in files:
        rel_path = entry["path"]
        note_type = entry.get("type", "note")

        try:
            frontmatter, body = storage.read_file(rel_path)
        except FileNotFoundError:
            print(f"  SKIP (missing): {rel_path}")
            continue

        # Skip personal notes — don't modify raw text
        if frontmatter.get("note_mode") == "personal":
            print(f"  SKIP (personal): {rel_path}")
            continue

        existing_links = extract_wikilinks(body)
        frontmatter_with_path = {**frontmatter, "target_path": rel_path}
        related = await find_related(body, frontmatter_with_path, storage, user_id)

        if not related:
            print(f"  No links: {rel_path}")
            continue

        new_stems = [r["stem"] for r in related]
        already_linked = set(existing_links)
        truly_new = [r for r in related if r["stem"] not in already_linked]

        if not truly_new:
            print(f"  Up to date ({len(existing_links)} links): {rel_path}")
            continue

        new_body = inject_links(body, related)

        print(f"  {'[DRY] ' if dry_run else ''}Linking: {rel_path}")
        for r in truly_new:
            print(f"    + [[{r['stem']}]] — {r['reason']}")

        if not dry_run:
            storage.write_file(rel_path, new_body, frontmatter)
            updated += 1

        # Small delay to avoid rate limits
        await asyncio.sleep(0.5)

    print(f"\nDone. Updated {updated}/{len(files)} notes.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing")
    args = parser.parse_args()

    asyncio.run(relink_user(args.user_id, dry_run=args.dry_run))
