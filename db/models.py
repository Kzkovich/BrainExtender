from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Float, Integer, String, create_engine
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config.settings import settings

engine = create_engine(settings.DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True)          # tg_user_id as string
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    profile_id = Column(String, default="universal")
    tariff = Column(String, default="free")        # free | pro | plus
    trial_ends_at = Column(DateTime, nullable=True)
    subscription_active = Column(Boolean, default=False)
    subscription_ends_at = Column(DateTime, nullable=True)
    active_workspace = Column(String, default="work")
    created_at = Column(DateTime, default=datetime.utcnow)


class UsageLog(Base):
    __tablename__ = "usage_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=False, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    operation = Column(String)                     # ingest | query | format
    tokens_in = Column(Integer, default=0)
    tokens_out = Column(Integer, default=0)
    model = Column(String)
    cost_usd = Column(Float, default=0.0)


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=False, index=True)
    amount = Column(Integer)                       # Telegram Stars или копейки
    currency = Column(String, default="XTR")       # XTR = Telegram Stars
    tariff = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)


def create_tables():
    Base.metadata.create_all(bind=engine)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
