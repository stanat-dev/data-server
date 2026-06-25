"""ORM 모델. backend-spring Flyway V1__init_schema.sql 의 external_places 와 1:1.

⚠️ 스키마 소유권은 backend-spring. 컬럼 추가/변경이 필요하면 backend-spring 에 PR.
여기 모델은 그 계약을 '따르기만' 한다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ExternalPlace(Base):
    __tablename__ = "external_places"

    external_place_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(20), default="TOURAPI")
    source_content_id: Mapped[str] = mapped_column(String(100))
    language: Mapped[str] = mapped_column(String(2), default="KO")
    name: Mapped[str] = mapped_column(String(200))
    address: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    lat: Mapped[float] = mapped_column(Numeric(10, 7))
    lng: Mapped[float] = mapped_column(Numeric(10, 7))
    tel: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    image_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    overview: Mapped[Optional[str]] = mapped_column(nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=False))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now()
    )
