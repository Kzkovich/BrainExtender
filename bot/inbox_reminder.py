import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path

from config.settings import settings

logger = logging.getLogger(__name__)

INBOX_TTL_DAYS = 7
CHECK_INTERVAL_SECONDS = 24 * 60 * 60  # once per day


async def start_inbox_reminder(bot):
    while True:
        try:
            await _check_all_users(bot)
        except Exception:
            logger.exception("Inbox reminder error")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


async def _check_all_users(bot):
    users_dir = settings.DATA_PATH / "users"
    if not users_dir.exists():
        return

    cutoff = datetime.utcnow() - timedelta(days=INBOX_TTL_DAYS)

    for user_dir in users_dir.iterdir():
        if not user_dir.is_dir():
            continue
        user_id = user_dir.name
        inbox = user_dir / "brain" / "_inbox"
        if not inbox.exists():
            continue

        old_files = []
        for f in inbox.glob("*.md"):
            mtime = datetime.utcfromtimestamp(f.stat().st_mtime)
            if mtime < cutoff:
                old_files.append(f)

        if old_files:
            try:
                await bot.send_message(
                    user_id,
                    f"📬 У тебя {len(old_files)} необработанных заметок во входящих "
                    f"(старше {INBOX_TTL_DAYS} дней).\n\n"
                    f"/inbox — посмотреть",
                )
            except Exception:
                pass  # User may have blocked the bot
