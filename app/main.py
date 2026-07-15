"""FastAPI 앱. 배치 수동 트리거 + 헬스체크.

크론은 cli.py(`python -m app.cli`)로도 돌릴 수 있다. 둘 다 services.ingest 를 공유.
열린 결정 §6.4: 트리거를 크론으로 고정할지/수동 유지할지는 운영에서 결정.
"""

from __future__ import annotations

import logging
import os
import time

from fastapi import FastAPI

from app import __version__
from app.schemas import (
    IngestRequest,
    IngestResult,
    RouteGenerateRequest,
    RouteGenerateResponse,
)
from app.services.ingest import run_ingest
from app.services.route_generator import generate_route
from app.services.route_generator_v2 import generate_route_v2

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

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


def _route_totals(resp: RouteGenerateResponse) -> tuple[int, int]:
    """섀도 비교용 요약 (총 이동 미터, 총 이동 분). 본문 덤프 금지 — logging 규칙."""
    dist_m = 0
    move_min = 0
    for day in resp.days:
        for item in day.items:
            dist_m += item.distance_meter_from_prev or 0
            move_min += item.move_minutes_from_prev or 0
    return dist_m, move_min


# exclude_unset: distance-v2 전용 additive 필드(day_load_minutes 등)가
# distance-v1 응답 wire 에 null 로 새지 않게 한다 (backend-spring 하위호환).
@app.post("/routes/generate", response_model=RouteGenerateResponse, response_model_exclude_unset=True)
def routes_generate(req: RouteGenerateRequest) -> RouteGenerateResponse:
    """경로 생성. 요청 payload 만 쓰는 순수 함수(DB 미접근), backend-spring 이 호출.

    algorithm=None → distance-v2 기본, "distance-v1" 로 요청 단위 롤백.
    """
    started = time.perf_counter()
    if req.algorithm == "distance-v1":
        result = generate_route(req)
    else:
        result = generate_route_v2(req)
        if os.getenv("ROUTE_SHADOW_COMPARE", "").lower() in ("1", "true", "yes"):
            v1_dist, v1_move = _route_totals(generate_route(req))
            v2_dist, v2_move = _route_totals(result)
            logger.info(
                "route shadow compare places=%s day_count=%s "
                "v1_dist_m=%s v2_dist_m=%s v1_move_min=%s v2_move_min=%s v2_max_load=%s",
                len(req.places),
                req.day_count,
                v1_dist,
                v2_dist,
                v1_move,
                v2_move,
                max((day.day_load_minutes or 0) for day in result.days),
            )
    # 요약 카운트만 남긴다(좌표/ref 목록 등 본문 덤프 금지 — logging 규칙).
    logger.info(
        "route generate done day_count=%s places=%s algorithm=%s elapsed_ms=%s",
        req.day_count,
        len(req.places),
        result.algorithm_version,
        round((time.perf_counter() - started) * 1000),
    )
    return result
