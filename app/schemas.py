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


class RoutePlaceIn(BaseModel):
    """경로 생성 입력 장소. ref 는 backend-spring 이 소유한 불투명 문자열(그대로 반환)."""

    ref: str
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    stay_minutes: Optional[int] = Field(None, ge=0, description="distance-v1 은 미사용, 일정구성용 예약")


class RouteGenerateRequest(BaseModel):

    day_count: int = Field(..., ge=1, le=30)
    places: list[RoutePlaceIn] = Field(..., min_length=1)


class RouteItemOut(BaseModel):
    """일자 내 방문 순서 1건. 각 일자 첫 항목의 거리/이동시간은 None."""

    ref: str
    sequence_no: int
    distance_meter_from_prev: Optional[int] = None
    move_minutes_from_prev: Optional[int] = None


class RouteDayOut(BaseModel):

    day_no: int
    items: list[RouteItemOut]


class RouteGenerateResponse(BaseModel):

    algorithm_version: str
    days: list[RouteDayOut]
