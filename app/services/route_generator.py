"""경로 생성(distance-v1): haversine + nearest-neighbor.

교체 지점: generate_route() 가 유일한 진입점이다. 알고리즘을 바꿀 때는
이 모듈 내부(또는 향후 요청의 algorithm 필드 분기)만 교체하고
main.py / 스키마 계약은 유지한다.

계약(정본은 tests/test_routes_api.py):
- places[0] 에서 시작해 최근접 이웃 순서로 방문 순서를 만든다.
- 순서화된 목록을 day_count 개의 연속 구간으로 나눈다. 나머지는 앞 일자부터
  하나씩 더 받는다(5곳/2일 → 3+2). 장소 수 < 일수면 뒤 일자는 빈 items.
- sequence_no 는 일자별 1부터. 각 일자 첫 항목의
  distance_meter_from_prev / move_minutes_from_prev 는 None
  (trip_place_items 의 nullable 컬럼과 동일 의미).
- 이동시간은 도보 가정: max(1, round(distance / WALK_METERS_PER_MINUTE)).

이 모듈은 math + app.schemas 외 import 금지(설정/DB 무관, 순수 함수 유지).
"""

from __future__ import annotations

import math

from app.schemas import (
    RouteDayOut,
    RouteGenerateRequest,
    RouteGenerateResponse,
    RouteItemOut,
    RoutePlaceIn,
)

ALGORITHM_VERSION = "distance-v1"
WALK_METERS_PER_MINUTE = 67  # 도보 약 4km/h
_EARTH_RADIUS_METERS = 6_371_000.0


def haversine_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * _EARTH_RADIUS_METERS * math.asin(math.sqrt(a))


def _nearest_neighbor_order(places: list[RoutePlaceIn]) -> list[RoutePlaceIn]:
    remaining = list(places[1:])
    ordered = [places[0]]
    while remaining:
        current = ordered[-1]
        nearest = min(
            remaining,
            key=lambda p: haversine_meters(current.lat, current.lng, p.lat, p.lng),
        )
        remaining.remove(nearest)
        ordered.append(nearest)
    return ordered


def _split_into_days(ordered: list[RoutePlaceIn], day_count: int) -> list[list[RoutePlaceIn]]:
    base, remainder = divmod(len(ordered), day_count)
    days: list[list[RoutePlaceIn]] = []
    cursor = 0
    for day_index in range(day_count):
        size = base + (1 if day_index < remainder else 0)
        days.append(ordered[cursor : cursor + size])
        cursor += size
    return days


def generate_route(req: RouteGenerateRequest) -> RouteGenerateResponse:
    ordered = _nearest_neighbor_order(req.places)
    day_chunks = _split_into_days(ordered, req.day_count)

    days: list[RouteDayOut] = []
    for day_index, chunk in enumerate(day_chunks):
        items: list[RouteItemOut] = []
        for seq_index, place in enumerate(chunk):
            if seq_index == 0:
                distance = None
                move_minutes = None
            else:
                prev = chunk[seq_index - 1]
                distance = round(haversine_meters(prev.lat, prev.lng, place.lat, place.lng))
                move_minutes = max(1, round(distance / WALK_METERS_PER_MINUTE))
            items.append(
                RouteItemOut(
                    ref=place.ref,
                    sequence_no=seq_index + 1,
                    distance_meter_from_prev=distance,
                    move_minutes_from_prev=move_minutes,
                )
            )
        days.append(RouteDayOut(day_no=day_index + 1, items=items))

    return RouteGenerateResponse(algorithm_version=ALGORITHM_VERSION, days=days)
