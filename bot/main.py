import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
import logging
from typing import Optional

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
from bot import persona
from bot.modules import get_applicable_modules
from brain.classifier import classify
from brain.deduplicator import check_before_save, enrich_existing
from brain.document_parser import parse_document, format_images_for_obsidian
from brain.formatter import format_content
from brain.indexer import update_index, update_brain_summary
from brain.linker import link_and_inject
from brain.profiles import ProfileLoader
from brain.storage import BrainStorage
from config.settings import settings
from core.quotas import check_quota, get_usage_since
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
        [InlineKeyboardButton(text="⚓ Сохранить", callback_data=f"ingest:save:{classification_id}")],
        [InlineKeyboardButton(text="✍️ Сохранить как личная заметка", callback_data=f"ingest:personal:{classification_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"ingest:cancel:{classification_id}")],
    ])


def _modules_keyboard(cid: str, classification) -> Optional[InlineKeyboardMarkup]:
    """Build keyboard with applicable module buttons after save.
    Uses pre-computed classification fields (task_probability etc.)."""
    from bot.modules import ALL_MODULES
    from bot.modules.todoist import TodoistModule

    buttons = []
    for m in ALL_MODULES:
        if isinstance(m, TodoistModule):
            show, label = m.can_handle_with_classification(classification)
            if show:
                buttons.append([InlineKeyboardButton(text=label, callback_data=f"module:{m.module_id}:{cid}")])
        else:
            if m.can_handle("", classification.content_type):
                buttons.append([InlineKeyboardButton(text=m.button_label, callback_data=f"module:{m.module_id}:{cid}")])

    return InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None


# Temporary in-memory store for pending ingests
_pending: dict[str, dict] = {}


@main_router.message(F.text, ~F.text.startswith("/"))
async def handle_ingest(msg: Message):
    user_id = str(msg.from_user.id)

    if _is_rate_limited(user_id):
        await msg.answer(persona.RATE_LIMITED)
        return

    with SessionLocal() as db:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            await msg.answer("Напиши /start чтобы начать.")
            return

    allowed, reason = await check_quota(user_id, "ingest")
    if not allowed:
        await msg.answer(persona.QUOTA_EXCEEDED)
        return

    status_msg = await msg.answer(persona.thinking())

    try:
        await _run_ingest_pipeline(msg.text, user_id, status_msg)
    except Exception as e:
        logger.exception("Ingest error")
        await status_msg.edit_text(f"{persona.error()}\n\n`{e}`", parse_mode="Markdown")


async def _run_ingest_pipeline(raw_text: str, user_id: str, status_msg, images: list[str] = None):
    """
    Full pipeline:
    1. Split content if it contains multiple topics
    2. For each chunk: classify → dedup → format → preview
    """
    import uuid
    storage = BrainStorage(user_id)
    meta = storage.get_meta()
    profile = ProfileLoader.load(meta.get("profile_id", "universal"))

    await status_msg.edit_text("🔱 Философствую над содержимым...")

    # One omnibus classify call — returns split decision + all metadata
    cid = await _process_single_chunk(raw_text, user_id, storage, profile, images=images)
    pending = _pending[cid]
    classification = pending["classification"]

    if classification.should_split and len(classification.split_chunks) > 1:
        # Multi-chunk flow — process each chunk from classify result
        chunks = classification.split_chunks
        await status_msg.edit_text(
            f"🌊 *Вижу {len(chunks)} смысловых потока.*\nОбрабатываю каждый...",
            parse_mode="Markdown",
        )
        # Remove the initial single-chunk pending (it was just to get split info)
        _pending.pop(cid, None)

        results = []
        for i, chunk in enumerate(chunks, 1):
            await status_msg.edit_text(
                f"🔱 Поток {i}/{len(chunks)}: *{chunk.get('title', '...')}*",
                parse_mode="Markdown",
            )
            chunk_cid = await _process_single_chunk(
                chunk.get("content", ""), user_id, storage, profile,
                images=images if i == 1 else None,
                hint=chunk.get("hint", ""),
            )
            results.append((chunk.get("title", ""), chunk_cid))

        for title, chunk_cid in results:
            p = _pending.get(chunk_cid)
            if not p:
                continue
            cl = p["classification"]
            await status_msg.answer(
                f"📋 *{cl.raw_title or title}*\nКуда: `{cl.target_path}`",
                parse_mode="Markdown",
                reply_markup=_ingest_preview_keyboard(chunk_cid),
            )
        await status_msg.edit_text(
            f"🌊 *{len(results)} потока готовы.* Проверь каждый выше.",
            parse_mode="Markdown",
        )
        return

    # Single chunk flow
    dedup = pending["dedup"]

    file_type = profile.get_file_type(classification.content_type)
    type_name = file_type.name if file_type else classification.content_type
    mode_icon = "📐" if classification.note_mode == "structured" else "✍️"

    dedup_line = ""
    if dedup.action == "update_existing":
        dedup_line = f"\n♻️ Обогатит: `{dedup.existing_path}`"
    elif dedup.action == "link_to_existing":
        dedup_line = f"\n🔗 Слинкует с: `{dedup.existing_path}`"

    img_line = f"\n🖼 Вложений: {len(images)}" if images else ""

    preview_text = (
        f"📋 *{classification.raw_title or 'Без названия'}*\n"
        f"Тип: {type_name}  {mode_icon}\n"
        f"Куда: `{classification.target_path}`"
        f"{dedup_line}{img_line}\n"
        f"Уверенность: {int(classification.confidence * 100)}%"
    )
    await status_msg.edit_text(
        preview_text,
        parse_mode="Markdown",
        reply_markup=_ingest_preview_keyboard(cid),
    )


async def _process_single_chunk(
    content: str,
    user_id: str,
    storage,
    profile,
    images: list[str] = None,
    hint: str = "",
) -> str:
    """Process one content chunk → returns cid stored in _pending."""
    import uuid
    if hint:
        content_for_classify = f"[Контекст: {hint}]\n\n{content}"
    else:
        content_for_classify = content

    classification = await classify(content_for_classify, user_id)
    dedup = await check_before_save(content, classification, storage, user_id)
    body, frontmatter = await format_content(content, classification, profile, user_id)

    if images:
        body = format_images_for_obsidian(images, body)

    cid = str(uuid.uuid4())[:8]
    _pending[cid] = {
        "raw_text": content,
        "body": body,
        "frontmatter": frontmatter,
        "classification": classification,
        "dedup": dedup,
        "user_id": user_id,
        "images": images or [],
    }
    return cid


@main_router.message(F.document)
async def handle_document(msg: Message):
    """Handle PDF, DOCX, TXT files sent to bot."""
    user_id = str(msg.from_user.id)

    if _is_rate_limited(user_id):
        await msg.answer(persona.RATE_LIMITED)
        return

    with SessionLocal() as db:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            await msg.answer("Напиши /start чтобы начать.")
            return

    allowed, reason = await check_quota(user_id, "ingest")
    if not allowed:
        await msg.answer(persona.QUOTA_EXCEEDED)
        return

    fname = msg.document.file_name or "документ"
    fsize_mb = round((msg.document.file_size or 0) / 1024 / 1024, 1)
    status_msg = await msg.answer(f"📄 *{fname}* ({fsize_mb} МБ)\n{persona.thinking()}", parse_mode="Markdown")

    try:
        await status_msg.edit_text(f"📄 *{fname}*\n⬇️ Скачиваю...", parse_mode="Markdown")
        file = await bot.get_file(msg.document.file_id)
        file_bytes = await bot.download_file(file.file_path, timeout=120)
        raw_bytes = file_bytes.read() if hasattr(file_bytes, "read") else bytes(file_bytes)

        await status_msg.edit_text(f"📄 *{fname}*\n🔍 Извлекаю текст и изображения...", parse_mode="Markdown")
        storage = BrainStorage(user_id)
        parsed = await parse_document(raw_bytes, fname, storage, user_id)

        if parsed.error:
            logger.error(f"Document parse error [{fname}]: {parsed.error}")
            await status_msg.edit_text(
                f"🌊 *Шторм при разборе документа*\n\n`{parsed.error}`",
                parse_mode="Markdown",
            )
            return

        if not parsed.text.strip():
            await status_msg.edit_text("🌊 Документ пуст или не содержит текста.")
            return

        pages_info = f" • {parsed.page_count} стр." if parsed.page_count else ""
        imgs_info = f" • {len(parsed.images)} изобр." if parsed.images else ""
        await status_msg.edit_text(
            f"📄 *{fname}*{pages_info}{imgs_info}\n🔱 Философствую над содержимым...",
            parse_mode="Markdown",
        )

        content = f"Файл: {fname}\n\n{parsed.text}"
        if msg.caption:
            content = f"{msg.caption}\n\n{content}"

        await _run_ingest_pipeline(content, user_id, status_msg, images=parsed.images)

    except Exception as e:
        logger.exception(f"Document ingest error [{fname}]")
        await status_msg.edit_text(
            f"🌊 *Шторм при обработке {fname}*\n\n`{type(e).__name__}: {e}`",
            parse_mode="Markdown",
        )


@main_router.message(F.photo)
async def handle_photo(msg: Message):
    """Handle photos — OCR + describe via Claude Vision."""
    user_id = str(msg.from_user.id)

    if _is_rate_limited(user_id):
        await msg.answer(persona.RATE_LIMITED)
        return

    with SessionLocal() as db:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            await msg.answer("Напиши /start чтобы начать.")
            return

    allowed, reason = await check_quota(user_id, "ingest")
    if not allowed:
        await msg.answer(persona.QUOTA_EXCEEDED)
        return

    status_msg = await msg.answer(f"🖼 {persona.thinking()}")

    try:
        # Get best quality photo
        photo = msg.photo[-1]
        file = await bot.get_file(photo.file_id)
        file_bytes = await bot.download_file(file.file_path, timeout=120)
        raw_bytes = file_bytes.read() if hasattr(file_bytes, "read") else bytes(file_bytes)

        storage = BrainStorage(user_id)
        parsed = await parse_document(raw_bytes, f"{photo.file_id}.jpg", storage, user_id)

        content = parsed.text
        if msg.caption:
            content = f"{msg.caption}\n\n{content}"

        if not content.strip():
            await status_msg.edit_text("🌊 Не удалось извлечь смысл из изображения.")
            return

        await _run_ingest_pipeline(content, user_id, status_msg, images=parsed.images)

    except Exception as e:
        logger.exception("Photo ingest error")
        await status_msg.edit_text(f"{persona.error()}\n\n`{e}`", parse_mode="Markdown")


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
    dedup = pending.get("dedup")

    try:
        from datetime import datetime as dt
        target_path = classification.target_path
        pipeline_start = pending.get("pipeline_start", dt.utcnow())

        # Records — append-only, never overwrite
        if classification.content_type in storage.RECORD_TYPES:
            storage.append_to_record(
                classification.content_type, body,
                title=classification.raw_title,
            )
            # Also index as regular file for manifest/search
            update_index(storage, target_path, frontmatter, body)
        elif dedup and dedup.action == "update_existing" and dedup.existing_path:
            # Enrich existing note
            try:
                existing_fm, existing_body = storage.read_file(dedup.existing_path)
                merged_body = await enrich_existing(
                    existing_body, pending["raw_text"],
                    dedup.merge_hint or "добавь новую информацию", user_id
                )
                storage.write_file(dedup.existing_path, merged_body, existing_fm)
                update_index(storage, dedup.existing_path, existing_fm, merged_body)
                target_path = dedup.existing_path
            except Exception:
                storage.write_file(target_path, body, frontmatter)
                update_index(storage, target_path, frontmatter, body)
        else:
            storage.write_file(target_path, body, frontmatter)
            update_index(storage, target_path, frontmatter, body)

        update_brain_summary(storage)
        _pending.pop(cid, None)

        usage = get_usage_since(user_id, pipeline_start)
        cost_line = (
            f"\n💸 `{usage.tokens_in + usage.tokens_out:,}` токенов"
            f" · `${usage.cost_usd:.4f}`"
        )

        action_label = "Обогатил" if dedup and dedup.action == "update_existing" else "Сохранил"
        await call.message.edit_text(
            f"⚓ *{action_label} в глубинах памяти.*\n`{target_path}`{cost_line}",
            parse_mode="Markdown",
        )

        # Show module buttons if applicable
        modules_kb = _modules_keyboard(cid, pending["classification"])
        if modules_kb:
            await call.message.answer(
                "🔱 *Что сделать с этой записью?*",
                parse_mode="Markdown",
                reply_markup=modules_kb,
            )

    except Exception as e:
        logger.exception("Save error")
        await call.message.edit_text(f"{persona.error()}\n\n`{e}`", parse_mode="Markdown")


@main_router.callback_query(lambda c: c.data and c.data.startswith("module:"))
async def handle_module(call: CallbackQuery):
    """Run a post-save module."""
    parts = call.data.split(":", 2)
    if len(parts) < 3:
        return
    _, module_id, cid = parts
    user_id = str(call.from_user.id)

    pending = _pending.get(cid)
    if not pending:
        await call.answer("Сессия истекла.", show_alert=True)
        return

    from bot.modules import ALL_MODULES
    module = next((m for m in ALL_MODULES if m.module_id == module_id), None)
    if not module:
        await call.answer("Модуль не найден.", show_alert=True)
        return

    await call.answer("🔱 Выполняю...")
    await call.message.edit_text(f"🌊 *{module.button_label}*\nФилософствую...", parse_mode="Markdown")

    result = await module.run(
        content=pending.get("raw_text", ""),
        user_id=user_id,
        extra={"classification": pending.get("classification")},
    )

    await call.message.edit_text(result.message, parse_mode="Markdown")


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
        persona.STATS_HEADER,
        f"",
        f"📁 Всего записей: {stats.get('total_files', 0)}",
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

    from core.quotas import _cost_today, _count_today, QUOTAS, _get_tariff
    effective_tariff = _get_tariff(user_id)
    quota = QUOTAS.get(effective_tariff, QUOTAS["free"])
    cost = _cost_today(user_id)
    ingests = _count_today(user_id, "ingest")
    queries = _count_today(user_id, "query")

    if effective_tariff == "owner":
        await msg.answer(
            f"💳 *Биллинг*\n\n"
            f"Тариф: *OWNER* ∞\n\n"
            f"Сегодня:\n"
            f"• Ингестов: {ingests}\n"
            f"• Запросов: {queries}\n"
            f"• API-расход: ${cost:.4f}",
            parse_mode="Markdown",
        )
        return

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
    await msg.answer(persona.HELP_TEXT, parse_mode="Markdown")


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
