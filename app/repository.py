
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.orm import Session

from app.models import ExternalPlace
from app.schemas import NormalizedPlace


def upsert_places(
    session: Session, places: Iterable[NormalizedPlace], fetched_at: datetime
) -> int:
    """정규화 장소들을 upsert. 반영된 행 수를 반환.

    MySQL/TiDB 에서 ON DUPLICATE KEY UPDATE 의 rowcount 는
    insert=1, update=2 로 집계되므로 '시도 건수'를 그대로 반환한다.
    """
    rows = [
        {
            "source": p.source,
            "source_content_id": p.source_content_id,
            "language": p.language,
            "name": p.name,
            "address": p.address,
            "lat": p.lat,
            "lng": p.lng,
            "tel": p.tel,
            "image_url": p.image_url,
            "overview": p.overview,
            "fetched_at": fetched_at,
        }
        for p in places
    ]
    if not rows:
        return 0

    stmt = mysql_insert(ExternalPlace).values(rows)
    # created_at/updated_at 은 DB default/onupdate 에 위임. 변동 컬럼만 갱신.
    stmt = stmt.on_duplicate_key_update(
        name=stmt.inserted.name,
        address=stmt.inserted.address,
        lat=stmt.inserted.lat,
        lng=stmt.inserted.lng,
        tel=stmt.inserted.tel,
        image_url=stmt.inserted.image_url,
        overview=stmt.inserted.overview,
        fetched_at=stmt.inserted.fetched_at,
    )
    session.execute(stmt)
    return len(rows)
