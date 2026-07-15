"""distance-v2 품질 벤치마크 (골든 픽스처):
- v2 총 felt 이동 ≤ v1 (동일 메트릭 비교)
- 일자 경로 자기교차 0 (무타입 픽스처 — 2-opt 수렴 인증서)
- 일자 부하 균형 max/mean ≤ 1.3
- 규칙 픽스처: 숙소 마지막
"""

from __future__ import annotations

import math

from app.schemas import RouteGenerateRequest, RoutePlaceIn
from app.services.route_generator import generate_route, haversine_meters
from app.services.route_generator_v2 import felt_minutes, generate_route_v2

# 서울 도심 실좌표 12곳 (일반 좌표 — 거리 타이 없음)
SEOUL_UNTYPED = [
    ("명동성당", 37.5633, 126.9873),
    ("경복궁", 37.5796, 126.9770),
    ("북촌한옥마을", 37.5826, 126.9831),
    ("인사동", 37.5744, 126.9856),
    ("남산타워", 37.5512, 126.9882),
    ("동대문", 37.5714, 127.0098),
    ("광장시장", 37.5701, 126.9998),
    ("덕수궁", 37.5658, 126.9752),
    ("서촌", 37.5794, 126.9707),
    ("익선동", 37.5720, 126.9890),
    ("홍대", 37.5563, 126.9236),
    ("이태원", 37.5346, 126.9945),
]

# 타입 포함 픽스처 (성지 4 / 식당 3 / 카페 2 / 숙소 1 / 관광 4)
SEOUL_TYPED = [
    ("성지1", 37.5633, 126.9873, "SACRED", 90),
    ("성지2", 37.5796, 126.9770, "SACRED", 120),
    ("성지3", 37.5826, 126.9831, "SACRED", 90),
    ("성지4", 37.5512, 126.9882, "SACRED", 60),
    ("식당1", 37.5744, 126.9856, "RESTAURANT", 60),
    ("식당2", 37.5701, 126.9998, "RESTAURANT", 60),
    ("식당3", 37.5658, 126.9752, "RESTAURANT", 60),
    ("카페1", 37.5720, 126.9890, "CAFE", 40),
    ("카페2", 37.5794, 126.9707, "CAFE", 40),
    ("숙소", 37.5714, 127.0098, "ACCOMMODATION", 0),
    ("관광1", 37.5563, 126.9236, "TOURIST_SPOT", 60),
    ("관광2", 37.5346, 126.9945, "TOURIST_SPOT", 60),
    ("관광3", 37.5748, 126.9947, "TOURIST_SPOT", 60),
    ("관광4", 37.5610, 126.9948, "TOURIST_SPOT", 60),
]


def _untyped_req(day_count: int) -> RouteGenerateRequest:
    places = [RoutePlaceIn(ref=name, lat=lat, lng=lng) for name, lat, lng in SEOUL_UNTYPED]
    return RouteGenerateRequest(day_count=day_count, places=places)


def _typed_req(day_count: int) -> RouteGenerateRequest:
    places = [
        RoutePlaceIn(ref=name, lat=lat, lng=lng, item_type=ty, stay_minutes=stay)
        for name, lat, lng, ty, stay in SEOUL_TYPED
    ]
    return RouteGenerateRequest(day_count=day_count, places=places)


def _total_felt(res, coords: dict[str, tuple[float, float]]) -> float:
    total = 0.0
    for day in res.days:
        for prev, cur in zip(day.items, day.items[1:]):
            (lat1, lng1), (lat2, lng2) = coords[prev.ref], coords[cur.ref]
            total += felt_minutes(haversine_meters(lat1, lng1, lat2, lng2))
    return total


def _day_crossings(res, coords: dict[str, tuple[float, float]]) -> int:
    """일자별 폴리라인의 자기교차 수 (평면 근사 — 도시 스케일에서 충분)."""
    mid_lat = math.radians(37.56)

    def xy(ref: str) -> tuple[float, float]:
        lat, lng = coords[ref]
        return (lng * math.cos(mid_lat), lat)

    def crosses(p1, p2, p3, p4) -> bool:
        def orient(a, b, c):
            v = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
            return 0 if abs(v) < 1e-15 else (1 if v > 0 else -1)

        return (
            orient(p1, p2, p3) * orient(p1, p2, p4) < 0
            and orient(p3, p4, p1) * orient(p3, p4, p2) < 0
        )

    count = 0
    for day in res.days:
        pts = [xy(item.ref) for item in day.items]
        segs = list(zip(pts, pts[1:]))
        for i in range(len(segs)):
            for j in range(i + 2, len(segs)):  # 인접 세그먼트 제외
                if crosses(*segs[i], *segs[j]):
                    count += 1
    return count


def test_v2_beats_v1_on_felt_and_has_no_crossings():
    coords = {name: (lat, lng) for name, lat, lng in SEOUL_UNTYPED}
    for day_count in (1, 2, 3):
        req = _untyped_req(day_count)
        v1 = generate_route(req)
        v2 = generate_route_v2(req)
        assert _total_felt(v2, coords) <= _total_felt(v1, coords) + 1e-6
        assert _day_crossings(v2, coords) == 0  # 2-opt 수렴 = 자기교차 제거


def test_v2_day_load_balance():
    res = generate_route_v2(_untyped_req(3))
    loads = [d.day_load_minutes for d in res.days if d.items]
    assert max(loads) / (sum(loads) / len(loads)) <= 1.3


def test_typed_fixture_rules_and_balance():
    res = generate_route_v2(_typed_req(3))
    types = {name: ty for name, _, _, ty, _ in SEOUL_TYPED}
    # 숙소는 자기 일자의 마지막
    for day in res.days:
        day_types = [types[i.ref] for i in day.items]
        for pos, ty in enumerate(day_types):
            if ty == "ACCOMMODATION":
                assert all(t == "ACCOMMODATION" for t in day_types[pos + 1 :])
    # 모든 성지 포함 (드롭 금지)
    refs = {i.ref for d in res.days for i in d.items}
    assert {"성지1", "성지2", "성지3", "성지4"} <= refs
    # 부하 균형 (규칙 우회 반영 후에도)
    loads = [d.day_load_minutes for d in res.days if d.items]
    assert max(loads) / (sum(loads) / len(loads)) <= 1.3
