"""POST /routes/generate 계약 테스트 — backend-spring 어댑터가 의존하는 wire format 의 정본.

여기 snake_case 키/구조를 바꾸면 backend-spring RouteGeneratorAdapter(wire record)도
함께 바꿔야 한다.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

CONTRACT_REQUEST = {
    "day_count": 2,
    "places": [
        {"ref": "EXTERNAL_PLACE:5", "lat": 37.5796, "lng": 126.9770, "stay_minutes": 60},
        {"ref": "SACRED_PLACE:101", "lat": 37.5563, "lng": 126.9236, "stay_minutes": 90},
    ],
}


def test_generate_route_contract_shape():
    resp = client.post("/routes/generate", json=CONTRACT_REQUEST)
    assert resp.status_code == 200
    body = resp.json()

    assert set(body.keys()) == {"algorithm_version", "days"}
    # algorithm 미지정 시 서버 기본은 distance-v2 (v1 고정은 algorithm="distance-v1")
    assert body["algorithm_version"] == "distance-v2"
    assert [d["day_no"] for d in body["days"]] == [1, 2]

    first_item = body["days"][0]["items"][0]
    assert set(first_item.keys()) == {
        "ref",
        "sequence_no",
        "distance_meter_from_prev",
        "move_minutes_from_prev",
    }
    # places[0] 에서 시작 + 각 일자 첫 항목은 null
    assert first_item["ref"] == "EXTERNAL_PLACE:5"
    assert first_item["sequence_no"] == 1
    assert first_item["distance_meter_from_prev"] is None
    assert first_item["move_minutes_from_prev"] is None

    # ref 는 불투명 passthrough — 요청에 넣은 값이 그대로 돌아온다.
    returned_refs = {i["ref"] for d in body["days"] for i in d["items"]}
    assert returned_refs == {"EXTERNAL_PLACE:5", "SACRED_PLACE:101"}


def test_generate_route_rejects_empty_places():
    resp = client.post("/routes/generate", json={"day_count": 1, "places": []})
    assert resp.status_code == 422


def test_generate_route_rejects_out_of_range():
    resp = client.post(
        "/routes/generate",
        json={"day_count": 0, "places": CONTRACT_REQUEST["places"]},
    )
    assert resp.status_code == 422

    resp = client.post(
        "/routes/generate",
        json={"day_count": 1, "places": [{"ref": "X", "lat": 95.0, "lng": 127.0}]},
    )
    assert resp.status_code == 422
