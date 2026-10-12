"""Public presentation metadata shared across owners and server restarts."""
from datetime import datetime
from sqlalchemy import String, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class CollectionArtwork(Base):
    __tablename__ = 'collection_artwork'
    key: Mapped[str] = mapped_column(String(150), primary_key=True)
    collection_slug: Mapped[str | None] = mapped_column(String(100), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    refresh_after: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    stale_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
