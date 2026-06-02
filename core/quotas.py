from datetime import datetime, date
from typing import NamedTuple

from sqlalchemy import func

from config.settings import settings
from db.models import SessionLocal, UsageLog, User


class UsageSummary(NamedTuple):
    tokens_in: int
    tokens_out: int
    cost_usd: float


def get_usage_since(user_id: str, since: datetime) -> UsageSummary:
    """Sum tokens and cost for a user since a given datetime."""
    with SessionLocal() as db:
        row = (
            db.query(
                func.coalesce(func.sum(UsageLog.tokens_in), 0),
                func.coalesce(func.sum(UsageLog.tokens_out), 0),
                func.coalesce(func.sum(UsageLog.cost_usd), 0.0),
            )
            .filter(UsageLog.user_id == user_id, UsageLog.timestamp >= since)
            .one()
        )
    return UsageSummary(int(row[0]), int(row[1]), float(row[2]))

QUOTAS: dict[str, dict] = {
    "free": {
        "ingests_per_day": 10,
        "queries_per_day": 20,
        "max_brain_size_mb": 50,
        "max_api_cost_per_day_usd": 0.50,
    },
    "pro": {
        "ingests_per_day": 100,
        "queries_per_day": 200,
        "max_brain_size_mb": 1000,
        "max_api_cost_per_day_usd": 3.00,
    },
    "plus": {
        "ingests_per_day": 500,
        "queries_per_day": 1000,
        "max_brain_size_mb": 5000,
        "max_api_cost_per_day_usd": 10.00,
    },
    "owner": {
        "ingests_per_day": 999_999,
        "queries_per_day": 999_999,
        "max_brain_size_mb": 999_999,
        "max_api_cost_per_day_usd": 999_999.00,
    },
}


def _get_tariff(user_id: str) -> str:
    if user_id in settings.owner_ids:
        return "owner"
    with SessionLocal() as db:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return "free"
        if user.tariff == "free" and user.trial_ends_at:
            if datetime.utcnow() > user.trial_ends_at:
                return "expired"
        return user.tariff


def _count_today(user_id: str, operation: str) -> int:
    today = date.today()
    with SessionLocal() as db:
        count = (
            db.query(func.count(UsageLog.id))
            .filter(
                UsageLog.user_id == user_id,
                UsageLog.operation == operation,
                func.date(UsageLog.timestamp) == today,
            )
            .scalar()
        )
    return count or 0


def _cost_today(user_id: str) -> float:
    today = date.today()
    with SessionLocal() as db:
        total = (
            db.query(func.sum(UsageLog.cost_usd))
            .filter(
                UsageLog.user_id == user_id,
                func.date(UsageLog.timestamp) == today,
            )
            .scalar()
        )
    return total or 0.0


async def check_quota(user_id: str, operation: str = "ingest") -> tuple[bool, str]:
    """Returns (allowed, reason). reason is empty string when allowed."""
    tariff = _get_tariff(user_id)
    if tariff == "expired":
        return False, "Триал истёк. Оформи подписку: /billing"

    quota = QUOTAS.get(tariff, QUOTAS["free"])

    op_key = f"{operation}s_per_day"
    if op_key in quota:
        used = _count_today(user_id, operation)
        if used >= quota[op_key]:
            return False, f"Дневной лимит {operation} исчерпан ({used}/{quota[op_key]}). /billing"

    cost = _cost_today(user_id)
    if cost >= quota["max_api_cost_per_day_usd"]:
        return False, f"Дневной бюджет API исчерпан (${cost:.2f}). /billing"

    return True, ""


async def log_usage(
    user_id: str,
    operation: str,
    tokens_in: int,
    tokens_out: int,
    model: str,
    cost_usd: float,
):
    with SessionLocal() as db:
        db.add(UsageLog(
            user_id=user_id,
            operation=operation,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            model=model,
            cost_usd=cost_usd,
        ))
        db.commit()
