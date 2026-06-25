"""배치 오케스트레이션: areaBasedList 페이지 루프 → 정규화 → upsert.

흐름은 roadmap §4 그대로. 단계별 카운트를 IngestResult 로 요약한다.
"""

from __future__ import annotations

import logging
from datetime import datetime

from app.config import Settings, get_settings
from app.db import session_scope
from app.repository import upsert_places
from app.schemas import IngestRequest, IngestResult, NormalizedPlace
from app.tourapi.client import TourApiClient
from app.tourapi.normalizer import normalize

logger = logging.getLogger(__name__)


def run_ingest(req: IngestRequest, settings: Settings | None = None) -> IngestResult:
    settings = settings or get_settings()
    started_at = datetime.now()
    fetched = skipped = 0
    normalized: list[NormalizedPlace] = []

    max_pages = req.max_pages if req.max_pages is not None else settings.batch_max_pages

    with TourApiClient(settings) as client:
        items = client.iter_area_based(
            area_code=req.area_code,
            sigungu_code=req.sigungu_code,
            content_type_id=req.content_type_id,
            max_pages=max_pages,
        )
        for item in items:
            fetched += 1
            place = normalize(item)
            if place is None:
                skipped += 1
                continue
            normalized.append(place)

    # fetched_at 은 '서버 now()' (roadmap: 마지막 수집 시각).
    fetched_at = datetime.now()
    upserted = 0
    if normalized:
        with session_scope() as session:
            upserted = upsert_places(session, normalized, fetched_at)

    result = IngestResult(
        fetched=fetched,
        skipped_no_coords=skipped,
        upserted=upserted,
        started_at=started_at,
        finished_at=datetime.now(),
    )
    logger.info(
        "ingest done fetched=%s skipped=%s upserted=%s", fetched, skipped, upserted
    )
    return result
