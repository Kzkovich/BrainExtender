from aiogram import Router
from bot import persona
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from brain.profiles import ProfileLoader
from brain.storage import BrainStorage
from db.models import SessionLocal, User, create_tables

router = Router()


class OnboardingStates(StatesGroup):
    choosing_profile = State()


def _profile_keyboard() -> InlineKeyboardMarkup:
    profiles = ProfileLoader.list_available()
    buttons = []
    icons = {
        "product_owner": "🎯",
        "project_manager": "📊",
        "researcher": "🔬",
        "universal": "🌐",
        "custom": "🛠️",
    }
    for p in profiles:
        icon = icons.get(p.profile_id, "•")
        buttons.append([
            InlineKeyboardButton(
                text=f"{icon} {p.display_name}",
                callback_data=f"onboard:profile:{p.profile_id}",
            )
        ])
    buttons.append([
        InlineKeyboardButton(text="🛠️ Создать свой профиль", callback_data="onboard:profile:custom")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _get_or_create_user(user_id: str, username: "Optional[str]", first_name: "Optional[str]") -> tuple:
    from datetime import datetime, timedelta
    with SessionLocal() as db:
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            return user, False
        user = User(
            id=user_id,
            username=username,
            first_name=first_name,
            tariff="free",
            trial_ends_at=datetime.utcnow() + timedelta(days=7),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user, True


@router.message(CommandStart())
async def cmd_start(msg: Message, state: FSMContext):
    user_id = str(msg.from_user.id)
    _, is_new = _get_or_create_user(
        user_id,
        msg.from_user.username,
        msg.from_user.first_name,
    )

    if is_new:
        await state.set_state(OnboardingStates.choosing_profile)
        await msg.answer(
            persona.WELCOME_NEW,
            parse_mode="Markdown",
            reply_markup=_profile_keyboard(),
        )
    else:
        storage = BrainStorage(user_id)
        from brain.indexer import get_manifest
        manifest = get_manifest(storage)
        stats = manifest.get("stats", {})
        name = msg.from_user.first_name or "путник"
        files = stats.get("total_files", 0)
        await msg.answer(
            persona.WELCOME_BACK.format(name=name, files=files),
            parse_mode="Markdown",
        )


@router.callback_query(lambda c: c.data and c.data.startswith("onboard:profile:"))
async def choose_profile(call: CallbackQuery, state: FSMContext):
    user_id = str(call.from_user.id)
    profile_id = call.data.split(":")[-1]

    if profile_id == "custom":
        ProfileLoader.create_custom(user_id)
        display = "Кастомный"
    else:
        profile = ProfileLoader.load(profile_id)
        display = profile.display_name

    # Update user profile in DB
    with SessionLocal() as db:
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            user.profile_id = profile_id
            db.commit()

    # Initialize brain storage with this profile
    storage = BrainStorage(user_id)
    storage.update_meta({"profile_id": profile_id})

    # Create default workspace dirs
    profile = ProfileLoader.load(profile_id)
    for ws in profile.default_workspaces:
        ws_dir = storage.root / ws.domain / ws.slug
        ws_dir.mkdir(parents=True, exist_ok=True)

    await state.clear()
    await call.message.edit_text(
        f"✅ Профиль выбран: *{display}*\n\n"
        f"Создаю твой brain...",
        parse_mode="Markdown",
    )
    await call.message.answer(
        persona.PROFILE_CHOSEN.format(profile=display),
        parse_mode="Markdown",
    )
