from datetime import datetime, date

from sqlalchemy import func

from db.models import SessionLocal, UsageLog, User

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
}


def _get_tariff(user_id: str) -> str:
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
