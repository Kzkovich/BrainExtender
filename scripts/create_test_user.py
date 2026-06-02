#!/usr/bin/env python3
"""
Usage:
  python scripts/create_test_user.py --user-id=test_user_1 --profile=product_owner
  python scripts/create_test_user.py --user-id=test_user_2 --profile=universal
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from brain.profiles import ProfileLoader
from brain.storage import BrainStorage
from db.models import SessionLocal, User, create_tables


def create_test_user(user_id: str, profile_id: str):
    print(f"Creating user '{user_id}' with profile '{profile_id}'...")

    create_tables()

    with SessionLocal() as db:
        existing = db.query(User).filter(User.id == user_id).first()
        if existing:
            print(f"  User '{user_id}' already exists — skipping DB insert.")
        else:
            from datetime import datetime, timedelta
            user = User(
                id=user_id,
                username=f"test_{user_id}",
                first_name=user_id,
                profile_id=profile_id,
                tariff="free",
                trial_ends_at=datetime.utcnow() + timedelta(days=30),
            )
            db.add(user)
            db.commit()
            print(f"  DB record created.")

    storage = BrainStorage(user_id)
    storage.update_meta({"profile_id": profile_id})
    print(f"  Brain storage initialized at: {storage.root}")

    profile = ProfileLoader.load(profile_id)
    for ws in profile.default_workspaces:
        ws_dir = storage.root / ws.domain / ws.slug
        ws_dir.mkdir(parents=True, exist_ok=True)
        print(f"  Workspace created: {ws.domain}/{ws.slug}")

    print(f"Done! User '{user_id}' is ready.\n")
    return storage


def test_isolation(user_id_1: str, user_id_2: str):
    print("Testing user isolation...")
    storage1 = BrainStorage(user_id_1)
    storage2 = BrainStorage(user_id_2)

    # Attempt cross-user path traversal
    try:
        evil_path = f"../../../users/{user_id_2}/meta.json"
        storage1.read_file(evil_path)
        print("  FAIL: Path traversal succeeded (should not happen!)")
    except Exception as e:
        print(f"  PASS: Path traversal blocked — {type(e).__name__}: {e}")

    print("Isolation test complete.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--profile", default="universal")
    parser.add_argument("--test-isolation", action="store_true")
    args = parser.parse_args()

    create_test_user(args.user_id, args.profile)

    if args.test_isolation:
        other = "test_user_isolation_target"
        create_test_user(other, "universal")
        test_isolation(args.user_id, other)
