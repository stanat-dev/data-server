"""환경설정. 모든 비밀/연결정보는 env 로만 주입한다 (.env-example 참고)."""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- TourAPI (공공데이터포털 한국관광공사 KorService2) ---
    tourapi_service_key: str = Field(..., alias="TOURAPI_SERVICE_KEY")
    tourapi_base_url: str = Field(
        "https://apis.data.go.kr/B551011/KorService2",
        alias="TOURAPI_BASE_URL",
    )
    # KorService2 연산명은 접미사 2 (areaBasedList2). 환경별 차이 대비로 분리.
    tourapi_area_based_op: str = Field("areaBasedList2", alias="TOURAPI_AREA_BASED_OP")
    tourapi_mobile_app: str = Field("stanat", alias="TOURAPI_MOBILE_APP")
    tourapi_timeout_seconds: float = Field(10.0, alias="TOURAPI_TIMEOUT_SECONDS")

    batch_num_of_rows: int = Field(100, alias="BATCH_NUM_OF_ROWS")
    batch_max_pages: Optional[int] = Field(None, alias="BATCH_MAX_PAGES")  # None = 끝까지
    batch_arrange: str = Field("C", alias="BATCH_ARRANGE")  # C=수정일순(이미지 있는 것 우선 A/Q/R 등)

    database_url: str = Field(..., alias="DATABASE_URL")
    db_echo: bool = Field(False, alias="DB_ECHO")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
