"""distance-v2 단위테스트:
- felt-cost 엔벨로프 (도보/대중교통 하한)
- multi-start NN 이 places[0] 시작 편향을 제거
- split-DP 가 체류시간을 반영해 일자 부하를 균형
- Held-Karp 가 작은 일자에서 완전탐색 최적과 일치
- 규칙 패스 (숙소 마지막 / 점심 창)
- 결정성 + 입력 순서 셔플 불변성
"""

from __future__ import annotations

import itertools
import random

from app.schemas import RouteGenerateRequest, RoutePlaceIn
from app.services.route_generator import generate_route, haversine_meters
from app.services.route_generator_v2 import (
    ALGORITHM_VERSION,
    TRANSIT_METERS_PER_MINUTE,
    TRANSIT_OVERHEAD_MINUTES,
    WALK_METERS_PER_MINUTE,
    _held_karp_path,
    felt_minutes,
    generate_route_v2,
)


def _place(ref: str, lat: float, lng: float, stay: int | None = None, item_type: str | None = None) -> RoutePlaceIn:
    return RoutePlaceIn(ref=ref, lat=lat, lng=lng, stay_minutes=stay, item_type=item_type)


def _req(day_count: int, places: list[RoutePlaceIn]) -> RouteGenerateRequest:
    return RouteGenerateRequest(day_count=day_count, places=places)


def _total_felt(res, places_by_ref) -> float:
    total = 0.0
    for day in res.days:
        for prev, cur in zip(day.items, day.items[1:]):
            a, b = places_by_ref[prev.ref], places_by_ref[cur.ref]
            total += felt_minutes(haversine_meters(a.lat, a.lng, b.lat, b.lng))
    return total


def test_felt_envelope_walk_vs_transit():
    # 짧은 구간은 도보가 싸다
    assert felt_minutes(500) == 500 / WALK_METERS_PER_MINUTE
    # 긴 구간은 대중교통 프록시가 싸다
    assert felt_minutes(5000) == TRANSIT_OVERHEAD_MINUTES + 5000 / TRANSIT_METERS_PER_MINUTE
    # 하한 엔벨로프 — 어느 쪽이든 min
    for d in (0, 100, 915, 916, 2000, 20000):
        walk = d / WALK_METERS_PER_MINUTE
        transit = TRANSIT_OVERHEAD_MINUTES + d / TRANSIT_METERS_PER_MINUTE
        assert felt_minutes(d) == min(walk, transit)


def test_multi_start_removes_first_place_bias():
    # places[0] 이 일직선의 '가운데' — v1(NN from places[0])은 지그재그, v2 는 단조 경로.
    places = [
        _place("MID", 37.50, 127.00),
        _place("E1", 37.51, 127.00),
        _place("E2", 37.52, 127.00),
        _place("W1", 37.49, 127.00),
        _place("W2", 37.48, 127.00),
    ]
    by_ref = {p.ref: p for p in places}
    v1 = generate_route(_req(1, places))
    v2 = generate_route_v2(_req(1, places))
    assert _total_felt(v2, by_ref) < _total_felt(v1, by_ref)
    # 단조 경로: 끝점에서 시작 (W2..E2 또는 E2..W2)
    refs = [i.ref for i in v2.days[0].items]
    assert refs in (["W2", "W1", "MID", "E1", "E2"], ["E2", "E1", "MID", "W1", "W2"])


def test_split_balances_stay_load():
    # P0 에 300분 체류 — v1 은 3+2 로 자르지만 v2 는 P0 쪽 일자를 가볍게 만들어야 한다.
    places = [
        _place("P0", 37.50, 127.00, stay=300),
        _place("P1", 37.51, 127.00, stay=60),
        _place("P2", 37.52, 127.00, stay=60),
        _place("P3", 37.53, 127.00, stay=60),
        _place("P4", 37.54, 127.00, stay=60),
    ]
    res = generate_route_v2(_req(2, places))
    day_of_p0 = next(d for d in res.days if any(i.ref == "P0" for i in d.items))
    assert len(day_of_p0.items) <= 2
    loads = [d.day_load_minutes for d in res.days]
    assert max(loads) < 300 + 60 + 60  # 3+2 분할이었다면 넘었을 값


def test_held_karp_matches_brute_force():
    rng = random.Random(42)
    coords = [(37.5 + rng.uniform(-0.05, 0.05), 127.0 + rng.uniform(-0.05, 0.05)) for _ in range(7)]
    felt = [
        [felt_minutes(haversine_meters(a[0], a[1], b[0], b[1])) for b in coords]
        for a in coords
    ]

    def path_cost(order):
        return sum(felt[a][b] for a, b in zip(order, order[1:]))

    hk = _held_karp_path(list(range(7)), felt)
    best = min(path_cost(p) for p in itertools.permutations(range(7)))
    assert abs(path_cost(hk) - best) < 1e-6


def test_rule_accommodation_is_last_in_day():
    # 거리 최적 순서상 숙소가 중간에 오는 배치 — 규칙 패스가 마지막으로 보낸다.
    places = [
        _place("A", 37.50, 127.00, item_type="TOURIST_SPOT"),
        _place("B", 37.51, 127.00, item_type="TOURIST_SPOT"),
        _place("HOTEL", 37.52, 127.00, item_type="ACCOMMODATION"),
        _place("C", 37.53, 127.00, item_type="TOURIST_SPOT"),
    ]
    res = generate_route_v2(_req(1, places))
    refs = [i.ref for i in res.days[0].items]
    assert refs[-1] == "HOTEL"


def test_rule_lunch_restaurant_not_first():
    # 식당이 경로의 한쪽 끝 — 거리 최적이면 09:30 도착(창 위반). 규칙 패스가 뒤로 민다.
    places = [
        _place("R", 37.50, 127.00, item_type="RESTAURANT"),
        _place("A", 37.51, 127.00, item_type="TOURIST_SPOT"),
        _place("B", 37.52, 127.00, item_type="TOURIST_SPOT"),
        _place("C", 37.53, 127.00, item_type="TOURIST_SPOT"),
    ]
    res = generate_route_v2(_req(1, places))
    refs = [i.ref for i in res.days[0].items]
    assert refs[0] != "R"
    assert refs.index("R") >= 2  # 도착 11:00 이후가 되는 슬롯


def test_invariants_fuzz_stdlib():
    types = [None, "SACRED", "TOURIST_SPOT", "RESTAURANT", "ACCOMMODATION", "CAFE", "ETC"]
    for seed in range(100):
        rng = random.Random(seed)
        n = rng.randint(1, 24)
        day_count = rng.randint(1, 8)
        places = [
            _place(
                f"P{i}",
                37.5 + rng.uniform(-0.1, 0.1),
                127.0 + rng.uniform(-0.1, 0.1),
                stay=rng.choice([None, 30, 60, 120]),
                item_type=rng.choice(types),
            )
            for i in range(n)
        ]
        res = generate_route_v2(_req(day_count, places))
        assert res.algorithm_version == ALGORITHM_VERSION
        assert len(res.days) == day_count
        refs = [i.ref for d in res.days for i in d.items]
        assert sorted(refs) == sorted(f"P{i}" for i in range(n))  # 전 장소 정확히 1회
        for day in res.days:
            assert [i.sequence_no for i in day.items] == list(range(1, len(day.items) + 1))
            assert day.day_load_minutes >= 0
            if day.items:
                assert day.items[0].distance_meter_from_prev is None
                assert day.items[0].move_minutes_from_prev is None
            for item in day.items[1:]:
                assert item.distance_meter_from_prev >= 0
                assert item.move_minutes_from_prev >= 1


def test_determinism_and_shuffle_invariance():
    rng = random.Random(3)
    places = [
        _place(f"P{i}", 37.5 + rng.uniform(-0.05, 0.05), 127.0 + rng.uniform(-0.05, 0.05))
        for i in range(8)
    ]
    first = generate_route_v2(_req(3, places))
    second = generate_route_v2(_req(3, places))
    assert first == second  # 완전 결정성

    shuffled = list(places)
    random.Random(9).shuffle(shuffled)
    third = generate_route_v2(_req(3, shuffled))
    # 입력 순서가 바뀌어도 (일반 좌표 = 거리 타이 없음) 일자 구성은 동일해야 한다.
    partition_a = [frozenset(i.ref for i in d.items) for d in first.days]
    partition_b = [frozenset(i.ref for i in d.items) for d in third.days]
    assert partition_a == partition_b
    by_ref = {p.ref: p for p in places}
    assert abs(_total_felt(first, by_ref) - _total_felt(third, by_ref)) < 1e-6
