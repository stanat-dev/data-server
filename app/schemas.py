"""정규화된 장소 DTO 와 API 요청/응답 모델."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class NormalizedPlace(BaseModel):
    """TourAPI 원본 1건을 external_places 컬럼에 맞춰 정규화한 결과."""

    source: str = "TOURAPI"
    source_content_id: str
    language: str = "KO"
    name: str
    address: Optional[str] = None
    lat: float
    lng: float
    tel: Optional[str] = None
    image_url: Optional[str] = None
    overview: Optional[str] = None


class IngestRequest(BaseModel):

    area_code: Optional[int] = Field(None, description="TourAPI areaCode (지역코드)")
    sigungu_code: Optional[int] = Field(None, description="TourAPI sigunguCode (시군구코드)")
    content_type_id: Optional[int] = Field(None, description="TourAPI contentTypeId")
    max_pages: Optional[int] = Field(None, description="가져올 최대 페이지 수 (None=끝까지)")


class IngestResult(BaseModel):
    """배치 실행 결과 요약."""

    fetched: int = 0  # TourAPI 에서 받은 원본 건수
    skipped_no_coords: int = 0  # 좌표 없어 제외
    upserted: int = 0  # external_places 에 반영(insert+update)
    started_at: datetime
    finished_at: datetime
