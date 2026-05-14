from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    last_seen: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), index=True
    )
    request_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    current_plan_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("plans.id"), nullable=True
    )

    searches: Mapped[list["SearchLog"]] = relationship("SearchLog", back_populates="user")
    current_plan: Mapped["Plan | None"] = relationship("Plan", foreign_keys=[current_plan_id])
    subscriptions: Mapped[list["Subscription"]] = relationship(
        "Subscription", back_populates="user"
    )
    credit_balance: Mapped["CreditBalance | None"] = relationship(
        "CreditBalance", back_populates="user", uselist=False
    )
    credit_transactions: Mapped[list["CreditTransaction"]] = relationship(
        "CreditTransaction", back_populates="user"
    )
    payments: Mapped[list["Payment"]] = relationship("Payment", back_populates="user")


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name_pt: Mapped[str] = mapped_column(String(128), nullable=False)
    name_en: Mapped[str] = mapped_column(String(128), nullable=False)

    articles: Mapped[list["Article"]] = relationship("Article", back_populates="category")


class Article(Base):
    __tablename__ = "articles"
    __table_args__ = (Index("ix_articles_category_year", "category_id", "year"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doi: Mapped[str] = mapped_column(String(256), unique=True, index=True, nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    authors_json: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    journal: Mapped[str | None] = mapped_column(String(512), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    pdf_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    oa_status: Mapped[str | None] = mapped_column(String(32), nullable=True)  # green/gold/closed
    citations: Mapped[int | None] = mapped_column(Integer, nullable=True)
    category_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("categories.id"), nullable=True, index=True
    )
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )

    category: Mapped["Category | None"] = relationship("Category", back_populates="articles")
    search_articles: Mapped[list["SearchArticle"]] = relationship(
        "SearchArticle", back_populates="article"
    )


class SearchLog(Base):
    __tablename__ = "search_logs"
    __table_args__ = (Index("ix_search_logs_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), index=True, nullable=False
    )
    query_raw: Mapped[str] = mapped_column(Text, nullable=False)
    query_normalized: Mapped[str] = mapped_column(Text, index=True, nullable=False)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    articles_returned: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), index=True, nullable=False
    )

    user: Mapped["User"] = relationship("User", back_populates="searches")
    search_articles: Mapped[list["SearchArticle"]] = relationship(
        "SearchArticle", back_populates="search"
    )


class SearchArticle(Base):
    __tablename__ = "search_articles"

    search_id: Mapped[int] = mapped_column(Integer, ForeignKey("search_logs.id"), primary_key=True)
    article_id: Mapped[int] = mapped_column(Integer, ForeignKey("articles.id"), primary_key=True)
    rank: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    search: Mapped["SearchLog"] = relationship("SearchLog", back_populates="search_articles")
    article: Mapped["Article"] = relationship("Article", back_populates="search_articles")


class CacheEntry(Base):
    __tablename__ = "cache_entries"

    query_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    query_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    response_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    hits: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), index=True, nullable=False
    )


# ── Billing (Fase 9 — SaaS de créditos) ──────────────────────────────────────


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    monthly_credits: Mapped[int] = mapped_column(Integer, nullable=False)
    price_brl_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    validity_days: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    is_free: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (Index("ix_subscriptions_user_status", "user_id", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    plan_id: Mapped[int] = mapped_column(Integer, ForeignKey("plans.id"), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default="active", nullable=False
    )  # active|cancelled|expired|past_due
    started_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    current_period_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    cancel_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), default="mercadopago", nullable=False)
    provider_subscription_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship("User", back_populates="subscriptions")
    plan: Mapped["Plan"] = relationship("Plan")


class CreditBalance(Base):
    __tablename__ = "credit_balances"

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), primary_key=True)
    balance: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    monthly_quota_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    quota_resets_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship("User", back_populates="credit_balance")


class CreditTransaction(Base):
    __tablename__ = "credit_transactions"
    __table_args__ = (
        Index("ix_credit_transactions_user_created", "user_id", "created_at"),
        Index("ix_credit_transactions_expires", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    delta: Mapped[int] = mapped_column(
        Integer, nullable=False
    )  # positivo = crédito, negativo = consumo
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    # purchase | consume | refund | monthly_reset | bonus | expiration
    search_log_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("search_logs.id"), nullable=True
    )
    payment_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("payments.id"), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="credit_transactions")


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        Index("ix_payments_user_status", "user_id", "status"),
        Index("ix_payments_event_id", "provider_event_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    plan_id: Mapped[int] = mapped_column(Integer, ForeignKey("plans.id"), nullable=False)
    amount_brl_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="BRL", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    # pending | paid | failed | refunded | disputed
    provider: Mapped[str] = mapped_column(String(32), default="mercadopago", nullable=False)
    provider_payment_ref: Mapped[str | None] = mapped_column(
        String(128), unique=True, nullable=True
    )
    provider_event_id: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    pix_qr_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    checkout_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="payments")
    plan: Mapped["Plan"] = relationship("Plan")
