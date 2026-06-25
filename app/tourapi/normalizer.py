"""TourAPI 원본 item → NormalizedPlace.

매핑 (roadmap §4):
  contentid     → source_content_id
  title         → name
  addr1(+addr2) → address
  mapx          → lng   (경도)   ⚠️ mapy/mapx 뒤바꾸지 말 것
  mapy          → lat   (위도)
  tel           → tel
  firstimage    → image_url
  source=TOURAPI, language=KO
좌표(mapx/mapy)가 없거나 0 이면 제외(lat/lng NOT NULL) → None 반환.
"""

from __future__ import annotations

from typing import Any, Optional

from app.schemas import NormalizedPlace


def _clean(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_coord(value: Any) -> Optional[float]:
    text = _clean(value)
    if text is None:
        return None
    try:
        coord = float(text)
    except ValueError:
        return None
    # TourAPI 는 좌표 미상 시 0 또는 빈값을 준다 → 제외 대상.
    return coord if coord != 0.0 else None


def normalize(item: dict[str, Any]) -> Optional[NormalizedPlace]:
    """원본 1건을 정규화. 좌표 없으면 None(=ingest 가 skip 집계)."""
    lng = _parse_coord(item.get("mapx"))
    lat = _parse_coord(item.get("mapy"))
    if lat is None or lng is None:
        return None

    content_id = _clean(item.get("contentid"))
    name = _clean(item.get("title"))
    if content_id is None or name is None:
        return None

    addr1 = _clean(item.get("addr1"))
    addr2 = _clean(item.get("addr2"))
    address = " ".join(p for p in (addr1, addr2) if p) or None

    return NormalizedPlace(
        source="TOURAPI",
        source_content_id=content_id,
        language="KO",
        name=name,
        address=address,
        lat=lat,
        lng=lng,
        tel=_clean(item.get("tel")),
        image_url=_clean(item.get("firstimage")),
        overview=None,  # areaBasedList 는 overview 미제공(detailCommon 영역)
    )
