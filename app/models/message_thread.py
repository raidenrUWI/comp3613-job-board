from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Index, text
from sqlmodel import Field, SQLModel


class MessageThread(SQLModel, table=True):
    __table_args__ = (
        Index(
            "uq_listing_message_thread",
            "listing_id",
            unique=True,
            sqlite_where=text("kind = 'listing'"),
            postgresql_where=text("kind = 'listing'"),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    kind: str
    application_id: Optional[int] = Field(default=None, index=True, unique=True)
    listing_id: int = Field(index=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=DateTime(timezone=True),
    )
