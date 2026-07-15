"""정규화된 장소 DTO 와 API 요청/응답 모델."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

# backend-spring TripPlaceItemType 과 1:1 (distance-v2 규칙 패스에서 사용)
PlaceItemType = Literal["SACRED", "TOURIST_SPOT", "RESTAURANT", "ACCOMMODATION", "CAFE", "ETC"]

RouteAlgorithm = Literal["distance-v1", "distance-v2"]


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
    stay_minutes: Optional[int] = Field(
        None, ge=0, description="체류 분. distance-v2 는 일자 부하/시계 계산에 사용(없으면 타입별 기본값)"
    )
    item_type: Optional[PlaceItemType] = Field(
        None, description="distance-v2 규칙 패스용. 요청 전체에 하나도 없으면 규칙 no-op"
    )


class RouteGenerateRequest(BaseModel):

    day_count: int = Field(..., ge=1, le=30)
    places: list[RoutePlaceIn] = Field(..., min_length=1)
    algorithm: Optional[RouteAlgorithm] = Field(
        None, description="None=서버 기본(distance-v2). 'distance-v1' 로 요청 단위 롤백 가능"
    )


class RouteItemOut(BaseModel):
    """일자 내 방문 순서 1건. 각 일자 첫 항목의 거리/이동시간은 None."""

    ref: str
    sequence_no: int
    distance_meter_from_prev: Optional[int] = None
    move_minutes_from_prev: Optional[int] = None


class RouteDayOut(BaseModel):
    """additive 필드(day_load_minutes, over_budget)는 distance-v2 만 설정.

    응답은 exclude_unset 직렬화라 distance-v1 경로에선 wire 에 나타나지 않는다
    (하위호환 — backend-spring 어댑터 무수정 동작).
    """

    day_no: int
    items: list[RouteItemOut]
    day_load_minutes: Optional[int] = Field(
        None, description="distance-v2: Σ체류 + Σ이동(felt) 분"
    )
    over_budget: Optional[bool] = Field(
        None, description="distance-v2: 일일 예산(600분) 초과 여부"
    )


class RouteGenerateResponse(BaseModel):

    algorithm_version: str
    days: list[RouteDayOut]
    suggested_day_count: Optional[int] = Field(
        None, description="distance-v2: 총부하가 day_count×600분을 넘을 때만 설정되는 권장 일수"
    )
