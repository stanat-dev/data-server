"""FastAPI 앱. 배치 수동 트리거 + 헬스체크.

크론은 cli.py(`python -m app.cli`)로도 돌릴 수 있다. 둘 다 services.ingest 를 공유.
열린 결정 §6.4: 트리거를 크론으로 고정할지/수동 유지할지는 운영에서 결정.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from app import __version__
from app.schemas import IngestRequest, IngestResult
from app.services.ingest import run_ingest

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="stanat data-server (TourAPI 배치 트랙)",
    version=__version__,
    description="TourAPI areaBasedList → 정규화 → external_places upsert",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.post("/ingest/area-based", response_model=IngestResult)
def ingest_area_based(req: IngestRequest) -> IngestResult:
    """동기 실행. 페이지 수가 많으면 max_pages 로 끊어서 호출 권장.

    TODO(운영): 장시간 작업이면 BackgroundTasks/큐로 분리 (지금은 YAGNI).
    """
    return run_ingest(req)
