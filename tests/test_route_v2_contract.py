"""POST /routes/generate — distance-v2 도입 후 wire 계약 (test_routes_api.py 를 보강).

- algorithm 디스패치: None → distance-v2 기본, "distance-v1" 핀 시 v1 wire 바이트 호환
  (additive 필드가 v1 응답에 null 로도 새지 않아야 한다 — exclude_unset)
- 열화 입력 계약 테이블 / 결정성 byte-equal / 422 / perf tripwire
"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app.main import app
from app.schemas import RouteGenerateRequest, RoutePlaceIn
from app.services.route_generator_v2 import DAILY_BUDGET_MINUTES, generate_route_v2

client = TestClient(app)

BASE_PLACES = [
    {"ref": "EXTERNAL_PLACE:5", "lat": 37.5796, "lng": 126.9770, "stay_minutes": 60},
    {"ref": "SACRED_PLACE:101", "lat": 37.5563, "lng": 126.9236, "stay_minutes": 90},
    {"ref": "SACRED_PLACE:102", "lat": 37.5633, "lng": 126.9873, "stay_minutes": 60},
]


def test_default_dispatches_to_v2_with_additive_day_fields():
    resp = client.post("/routes/generate", json={"day_count": 2, "places": BASE_PLACES})
    assert resp.status_code == 200
    body = resp.json()
    assert body["algorithm_version"] == "distance-v2"
    # 오버플로가 아니면 톱레벨은 v1 과 동일한 두 키 (suggested_day_count 미출현)
    assert set(body.keys()) == {"algorithm_version", "days"}
    for day in body["days"]:
        assert set(day.keys()) == {"day_no", "items", "day_load_minutes", "over_budget"}
        assert day["day_load_minutes"] >= 0
        assert day["over_budget"] is False


def test_algorithm_pin_v1_keeps_wire_byte_compatible():
    resp = client.post(
        "/routes/generate",
        json={"day_count": 2, "places": BASE_PLACES, "algorithm": "distance-v1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["algorithm_version"] == "distance-v1"
    assert set(body.keys()) == {"algorithm_version", "days"}
    for day in body["days"]:
        # v1 응답에는 additive 필드가 아예 나타나지 않는다 (null 도 금지)
        assert set(day.keys()) == {"day_no", "items"}
    # v1 의미론 유지: places[0] 시작
    assert body["days"][0]["items"][0]["ref"] == "EXTERNAL_PLACE:5"


def test_unknown_algorithm_and_item_type_rejected():
    resp = client.post(
        "/routes/generate",
        json={"day_count": 1, "places": BASE_PLACES, "algorithm": "distance-v3"},
    )
    assert resp.status_code == 422

    bad_place = {"ref": "X", "lat": 37.5, "lng": 127.0, "item_type": "SHRINE"}
    resp = client.post("/routes/generate", json={"day_count": 1, "places": [bad_place]})
    assert resp.status_code == 422


def test_more_days_than_places_gives_empty_trailing_days():
    resp = client.post(
        "/routes/generate",
        json={"day_count": 4, "places": BASE_PLACES},
    )
    body = resp.json()
    assert [d["day_no"] for d in body["days"]] == [1, 2, 3, 4]
    assert [len(d["items"]) for d in body["days"]].count(1) == 3
    assert body["days"][3]["items"] == []
    assert body["days"][3]["day_load_minutes"] == 0
    assert body["days"][3]["over_budget"] is False


def test_single_place_and_duplicate_coordinates():
    resp = client.post(
        "/routes/generate",
        json={"day_count": 1, "places": [{"ref": "ONLY", "lat": 37.5, "lng": 127.0}]},
    )
    body = resp.json()
    only = body["days"][0]["items"][0]
    assert only["ref"] == "ONLY"
    assert only["distance_meter_from_prev"] is None

    dup = [
        {"ref": "A", "lat": 37.5, "lng": 127.0},
        {"ref": "B", "lat": 37.5, "lng": 127.0},  # 동일 좌표
        {"ref": "C", "lat": 37.51, "lng": 127.0},
    ]
    resp = client.post("/routes/generate", json={"day_count": 1, "places": dup})
    body = resp.json()
    items = body["days"][0]["items"]
    assert {i["ref"] for i in items} == {"A", "B", "C"}
    for item in items[1:]:
        assert item["move_minutes_from_prev"] >= 1  # v1 과 동일: 0m 구간도 최소 1분


def test_over_budget_sets_suggested_day_count():
    heavy = [
        {"ref": f"H{i}", "lat": 37.5 + i * 0.01, "lng": 127.0, "stay_minutes": 400}
        for i in range(4)
    ]
    resp = client.post("/routes/generate", json={"day_count": 1, "places": heavy})
    body = resp.json()
    day = body["days"][0]
    assert day["over_budget"] is True
    assert day["day_load_minutes"] > DAILY_BUDGET_MINUTES
    assert body["suggested_day_count"] >= 3  # 1600분+ / 600분 → 최소 3일 역제안
    assert body["suggested_day_count"] * DAILY_BUDGET_MINUTES >= day["day_load_minutes"]


def test_response_is_byte_identical_across_runs():
    payload = {"day_count": 3, "places": BASE_PLACES + [
        {"ref": "SACRED_PLACE:103", "lat": 37.5512, "lng": 126.9882, "item_type": "SACRED"},
        {"ref": "EXTERNAL_PLACE:9", "lat": 37.5714, "lng": 127.0098, "item_type": "RESTAURANT"},
    ]}
    first = client.post("/routes/generate", json=payload)
    second = client.post("/routes/generate", json=payload)
    assert first.content == second.content


def test_perf_tripwire_n50_d7():
    places = [
        RoutePlaceIn(
            ref=f"P{i}",
            lat=37.5 + (i * 37 % 100) * 0.0016 - 0.08,
            lng=127.0 + (i * 61 % 100) * 0.0016 - 0.08,
        )
        for i in range(50)
    ]
    req = RouteGenerateRequest(day_count=7, places=places)
    started = time.perf_counter()
    generate_route_v2(req)
    elapsed = time.perf_counter() - started
    # 실측 여유 포함 상한 — O(n⁴)/무한루프 회귀 감지용 (read-timeout 10s 대비 충분한 마진)
    assert elapsed < 0.5, f"distance-v2 took {elapsed * 1000:.0f}ms for n=50/d=7"
