"""경로 생성(distance-v1) 단위테스트:
- haversine 근사 정확성
- nearest-neighbor 방문 순서
- 일자 분할(나머지는 앞 일자 우선) / sequence_no 일자별 리셋 / 첫 항목 None
- 결정성
"""

from __future__ import annotations

from app.schemas import RouteGenerateRequest, RoutePlaceIn
from app.services.route_generator import (
    ALGORITHM_VERSION,
    generate_route,
    haversine_meters,
)


def _place(ref: str, lat: float, lng: float) -> RoutePlaceIn:
    return RoutePlaceIn(ref=ref, lat=lat, lng=lng)


def _req(day_count: int, places: list[RoutePlaceIn]) -> RouteGenerateRequest:
    return RouteGenerateRequest(day_count=day_count, places=places)


def test_haversine_known_distance():
    # 위도 0.01도 ≈ 1112m (경도 고정)
    d = haversine_meters(37.50, 127.00, 37.51, 127.00)
    assert abs(d - 1112) < 5


def test_nearest_neighbor_orders_by_proximity():
    # 같은 경도 위의 일직선 배치를 섞어서 넣어도 시작점에서 가까운 순으로 이어져야 한다.
    places = [
        _place("A", 37.50, 127.00),  # 시작점
        _place("C", 37.52, 127.00),
        _place("B", 37.51, 127.00),
        _place("D", 37.53, 127.00),
    ]
    res = generate_route(_req(1, places))
    refs = [item.ref for item in res.days[0].items]
    assert refs == ["A", "B", "C", "D"]


def test_split_five_places_two_days_is_three_plus_two():
    places = [_place(f"P{i}", 37.50 + i * 0.01, 127.00) for i in range(5)]
    res = generate_route(_req(2, places))
    assert [d.day_no for d in res.days] == [1, 2]
    assert [len(d.items) for d in res.days] == [3, 2]


def test_sequence_resets_per_day_and_first_item_has_none():
    places = [_place(f"P{i}", 37.50 + i * 0.01, 127.00) for i in range(4)]
    res = generate_route(_req(2, places))
    for day in res.days:
        assert [item.sequence_no for item in day.items] == list(range(1, len(day.items) + 1))
        assert day.items[0].distance_meter_from_prev is None
        assert day.items[0].move_minutes_from_prev is None
        for item in day.items[1:]:
            assert item.distance_meter_from_prev > 0
            assert item.move_minutes_from_prev >= 1


def test_more_days_than_places_gives_empty_trailing_days():
    res = generate_route(_req(3, [_place("A", 37.50, 127.00)]))
    assert len(res.days) == 3
    assert len(res.days[0].items) == 1
    assert res.days[1].items == []
    assert res.days[2].items == []


def test_algorithm_version_and_determinism():
    places = [
        _place("A", 37.5796, 126.9770),
        _place("B", 37.5563, 126.9236),
        _place("C", 37.5512, 126.9882),
    ]
    first = generate_route(_req(2, places))
    second = generate_route(_req(2, places))
    assert first.algorithm_version == ALGORITHM_VERSION == "distance-v1"
    assert first == second
