"""정규화 단위테스트 (roadmap §8 검증):
- mapx→lng / mapy→lat 정확성 (뒤바뀌지 않음)
- 좌표 없는 항목 필터
- addr1(+addr2) 합성
"""

from __future__ import annotations

import json
from pathlib import Path

from app.tourapi.client import _extract_items
from app.tourapi.normalizer import normalize

FIXTURE = Path(__file__).parent / "fixtures" / "area_based_list_sample.json"


def _load_items() -> list[dict]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    items, total = _extract_items(payload)
    assert total == 3
    return items


def test_mapx_is_lng_mapy_is_lat():
    items = _load_items()
    place = normalize(items[0])  # 경복궁
    assert place is not None
    # 경복궁: 경도 ~126.97, 위도 ~37.57 — 뒤바뀌면 위도가 126이 되어 실패한다.
    assert abs(place.lng - 126.9769930325) < 1e-6
    assert abs(place.lat - 37.5760836609) < 1e-6
    assert 33 < place.lat < 39  # 한국 위도 범위
    assert 124 < place.lng < 132  # 한국 경도 범위


def test_skips_item_without_coords():
    items = _load_items()
    assert normalize(items[1]) is None  # mapx/mapy 빈 문자열 → 제외


def test_address_concatenation_and_fields():
    items = _load_items()
    place = normalize(items[0])
    assert place is not None
    assert place.source == "TOURAPI"
    assert place.language == "KO"
    assert place.source_content_id == "126508"
    assert place.name == "경복궁"
    assert place.address == "서울특별시 종로구 사직로 161 (세종로)"
    assert place.tel == "02-3700-3900"
    assert place.image_url == "http://tong.visitkorea.or.kr/cms/gyeongbokgung.jpg"
    assert place.overview is None


def test_empty_optional_fields_become_none():
    items = _load_items()
    place = normalize(items[2])  # 북촌한옥마을: tel/firstimage 빈값
    assert place is not None
    assert place.tel is None
    assert place.image_url is None
    assert place.address == "서울특별시 종로구 계동길 37"  # addr2 빈값은 무시
