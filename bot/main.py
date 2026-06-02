import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.inbox_reminder import start_inbox_reminder
from bot.onboarding import router as onboarding_router
from brain.classifier import classify
from brain.formatter import format_content
from brain.indexer import update_index
from brain.profiles import ProfileLoader
from brain.storage import BrainStorage
from config.settings import settings
from core.quotas import check_quota
from db.models import SessionLocal, User, create_tables

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot: Bot = None  # initialized in main()
dp: Dispatcher = None  # initialized in main()

main_router = Router()

# Per-user rate limiting (in-memory, 5 msg/min)
_rate_limiter: dict[str, list[float]] = {}


def _is_rate_limited(user_id: str) -> bool:
    import time
    now = time.time()
    window = _rate_limiter.setdefault(user_id, [])
    # keep only timestamps within last 60s
    _rate_limiter[user_id] = [t for t in window if now - t < 60]
    if len(_rate_limiter[user_id]) >= 5:
        return True
    _rate_limiter[user_id].append(now)
    return False


def _ingest_preview_keyboard(classification_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Сохранить", callback_data=f"ingest:save:{classification_id}")],
        [InlineKeyboardButton(text="📝 Сохранить как личная заметка", callback_data=f"ingest:personal:{classification_id}")],
        [InlineKeyboardButton(text="✏️ Изменить тип", callback_data=f"ingest:retype:{classification_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"ingest:cancel:{classification_id}")],
    ])


# Temporary in-memory store for pending ingests
_pending: dict[str, dict] = {}


@main_router.message(F.text, ~F.text.startswith("/"))
async def handle_ingest(msg: Message):
    user_id = str(msg.from_user.id)

    if _is_rate_limited(user_id):
        await msg.answer("⏳ Слишком много сообщений. Подожди минуту.")
        return

    # Check if user exists and has profile set
    with SessionLocal() as db:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            await msg.answer("Напиши /start чтобы начать.")
            return

    allowed, reason = await check_quota(user_id, "ingest")
    if not allowed:
        await msg.answer(f"⚠️ {reason}")
        return

    status_msg = await msg.answer("🔍 Анализирую...")

    try:
        classification = await classify(msg.text, user_id)

        storage = BrainStorage(user_id)
        meta = storage.get_meta()
        profile = ProfileLoader.load(meta.get("profile_id", "universal"))
        body, frontmatter = await format_content(msg.text, classification, profile, user_id)

        # Store pending ingest
        import uuid
        cid = str(uuid.uuid4())[:8]
        _pending[cid] = {
            "raw_text": msg.text,
            "body": body,
            "frontmatter": frontmatter,
            "classification": classification,
            "user_id": user_id,
        }

        file_type = profile.get_file_type(classification.content_type)
        type_name = file_type.name if file_type else classification.content_type
        mode_icon = "📐" if classification.note_mode == "structured" else "✍️"
        mode_label = "Structured" if classification.note_mode == "structured" else "Personal"

        preview_text = (
            f"📋 *{classification.raw_title or 'Без названия'}*\n"
            f"Тип: {type_name}\n"
            f"Куда: `{classification.target_path}`\n"
            f"Режим: {mode_icon} {mode_label}\n"
            f"Уверенность: {int(classification.confidence * 100)}%"
        )

        await status_msg.edit_text(
            preview_text,
            parse_mode="Markdown",
            reply_markup=_ingest_preview_keyboard(cid),
        )
    except Exception as e:
        logger.exception("Ingest error")
        await status_msg.edit_text(f"❌ Ошибка при анализе: {e}")


@main_router.callback_query(lambda c: c.data and c.data.startswith("ingest:"))
async def handle_ingest_action(call: CallbackQuery):
    _, action, cid = call.data.split(":", 2)
    user_id = str(call.from_user.id)

    pending = _pending.get(cid)
    if not pending or pending["user_id"] != user_id:
        await call.answer("Сессия истекла. Отправь текст ещё раз.")
        return

    if action == "cancel":
        _pending.pop(cid, None)
        await call.message.edit_text("❌ Отменено.")
        return

    if action == "personal":
        pending["classification"].note_mode = "personal"
        pending["body"] = pending["raw_text"]

    storage = BrainStorage(user_id)
    classification = pending["classification"]
    body = pending["body"]
    frontmatter = pending["frontmatter"]
    frontmatter["note_mode"] = classification.note_mode

    try:
        storage.write_file(classification.target_path, body, frontmatter)
        update_index(storage, classification.target_path, frontmatter, body)
        _pending.pop(cid, None)

        await call.message.edit_text(
            f"✅ *Сохранено!*\n`{classification.target_path}`",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.exception("Save error")
        await call.message.edit_text(f"❌ Ошибка сохранения: {e}")


@main_router.message(Command("stats"))
async def cmd_stats(msg: Message):
    user_id = str(msg.from_user.id)
    storage = BrainStorage(user_id)
    from brain.indexer import get_manifest
    manifest = get_manifest(storage)
    stats = manifest.get("stats", {})

    by_type = stats.get("by_type", {})
    by_ws = stats.get("by_workspace", {})

    lines = [
        f"🧠 *Статистика brain*",
        f"",
        f"📁 Всего файлов: {stats.get('total_files', 0)}",
        f"",
        f"*По типам:*",
    ]
    for t, count in sorted(by_type.items(), key=lambda x: -x[1]):
        lines.append(f"  • {t}: {count}")
    lines.append("")
    lines.append("*По воркспейсам:*")
    for w, count in sorted(by_ws.items(), key=lambda x: -x[1]):
        lines.append(f"  • {w}: {count}")

    await msg.answer("\n".join(lines), parse_mode="Markdown")


@main_router.message(Command("profile"))
async def cmd_profile(msg: Message):
    user_id = str(msg.from_user.id)
    storage = BrainStorage(user_id)
    meta = storage.get_meta()
    profile = ProfileLoader.load(meta.get("profile_id", "universal"))

    profiles = ProfileLoader.list_available()
    buttons = []
    for p in profiles:
        mark = "✅ " if p.profile_id == profile.profile_id else ""
        buttons.append([
            InlineKeyboardButton(
                text=f"{mark}{p.display_name}",
                callback_data=f"profile:set:{p.profile_id}",
            )
        ])

    await msg.answer(
        f"👤 Текущий профиль: *{profile.display_name}*\n\n"
        f"{profile.description}\n\nВыбери другой:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@main_router.callback_query(lambda c: c.data and c.data.startswith("profile:set:"))
async def handle_profile_set(call: CallbackQuery):
    user_id = str(call.from_user.id)
    profile_id = call.data.split(":")[-1]

    profile = ProfileLoader.load(profile_id)
    storage = BrainStorage(user_id)
    storage.update_meta({"profile_id": profile_id})

    with SessionLocal() as db:
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            user.profile_id = profile_id
            db.commit()

    await call.message.edit_text(f"✅ Профиль изменён на *{profile.display_name}*", parse_mode="Markdown")


@main_router.message(Command("workspace"))
async def cmd_workspace(msg: Message):
    user_id = str(msg.from_user.id)
    storage = BrainStorage(user_id)
    meta = storage.get_meta()
    profile = ProfileLoader.load(meta.get("profile_id", "universal"))
    current = meta.get("active_workspace", "work")

    buttons = []
    for ws in profile.default_workspaces:
        mark = "✅ " if ws.slug == current else ""
        buttons.append([
            InlineKeyboardButton(
                text=f"{mark}{ws.name}",
                callback_data=f"workspace:set:{ws.slug}",
            )
        ])

    await msg.answer(
        f"📂 Активный воркспейс: *{current}*\n\nВыбери:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@main_router.callback_query(lambda c: c.data and c.data.startswith("workspace:set:"))
async def handle_workspace_set(call: CallbackQuery):
    user_id = str(call.from_user.id)
    slug = call.data.split(":")[-1]
    storage = BrainStorage(user_id)
    storage.update_meta({"active_workspace": slug})
    await call.message.edit_text(f"✅ Воркспейс переключён на *{slug}*", parse_mode="Markdown")


@main_router.message(Command("inbox"))
async def cmd_inbox(msg: Message):
    user_id = str(msg.from_user.id)
    storage = BrainStorage(user_id)
    files = storage.get_inbox_files()
    if not files:
        await msg.answer("📬 Входящие пусты.")
        return
    lines = [f"📬 *Входящие ({len(files)} файлов):*"]
    for f in files[:10]:
        lines.append(f"• {f.name}")
    await msg.answer("\n".join(lines), parse_mode="Markdown")


@main_router.message(Command("billing"))
async def cmd_billing(msg: Message):
    user_id = str(msg.from_user.id)
    with SessionLocal() as db:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            await msg.answer("Напиши /start")
            return
        tariff = user.tariff
        trial_ends = user.trial_ends_at

    from core.quotas import _cost_today, _count_today, QUOTAS
    quota = QUOTAS.get(tariff, QUOTAS["free"])
    cost = _cost_today(user_id)
    ingests = _count_today(user_id, "ingest")
    queries = _count_today(user_id, "query")

    trial_info = ""
    if tariff == "free" and trial_ends:
        from datetime import datetime
        days_left = (trial_ends - datetime.utcnow()).days
        trial_info = f"\n⏳ Триал: {max(0, days_left)} дней осталось"

    await msg.answer(
        f"💳 *Биллинг*\n\n"
        f"Тариф: *{tariff.upper()}*{trial_info}\n\n"
        f"Сегодня:\n"
        f"• Ингестов: {ingests}/{quota['ingests_per_day']}\n"
        f"• Запросов: {queries}/{quota['queries_per_day']}\n"
        f"• API-расход: ${cost:.4f}/${quota['max_api_cost_per_day_usd']:.2f}",
        parse_mode="Markdown",
    )


@main_router.message(Command("help"))
async def cmd_help(msg: Message):
    await msg.answer(
        "🧠 *Расширитель Мозга — команды*\n\n"
        "Просто напиши любой текст — сохраню в brain автоматически.\n\n"
        "/start — статус brain\n"
        "/stats — статистика\n"
        "/profile — сменить профиль\n"
        "/workspace — переключить воркспейс\n"
        "/inbox — необработанные файлы\n"
        "/billing — тариф и расход\n"
        "/help — эта справка",
        parse_mode="Markdown",
    )


async def main():
    global bot, dp
    bot = Bot(token=settings.TELEGRAM_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    create_tables()
    dp.include_router(onboarding_router)
    dp.include_router(main_router)

    asyncio.create_task(start_inbox_reminder(bot))

    logger.info("Bot starting...")
    await dp.start_polling(bot, allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    asyncio.run(main())
