"""TourAPI areaBasedList 클라이언트. httpx + tenacity(재시도).

응답을 페이지 단위로 yield 한다. 정규화/필터는 호출측(normalizer/ingest) 책임.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any, Optional

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import Settings

logger = logging.getLogger(__name__)


class TourApiError(RuntimeError):
    """TourAPI 가 정상 응답 형태가 아닐 때."""


class TourApiClient:
    def __init__(self, settings: Settings, client: Optional[httpx.Client] = None):
        self._settings = settings
        self._client = client or httpx.Client(timeout=settings.tourapi_timeout_seconds)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "TourApiClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError, TourApiError)),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def _fetch_page(self, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._settings.tourapi_base_url}/{self._settings.tourapi_area_based_op}"
        resp = self._client.get(url, params=params)
        resp.raise_for_status()
        # TourAPI 는 에러 시에도 200 + XML 을 줄 때가 있어 content-type 으로 방어.
        ctype = resp.headers.get("content-type", "")
        if "json" not in ctype.lower():
            raise TourApiError(f"비-JSON 응답: content-type={ctype!r} body={resp.text[:200]!r}")
        return resp.json()

    def iter_area_based(
        self,
        *,
        area_code: Optional[int] = None,
        sigungu_code: Optional[int] = None,
        content_type_id: Optional[int] = None,
        max_pages: Optional[int] = None,
    ) -> Iterator[dict[str, Any]]:
        """areaBasedList 의 item(원본 dict) 들을 페이지 루프로 순회."""
        page_no = 1
        num_of_rows = self._settings.batch_num_of_rows
        pages_seen = 0
        while True:
            params: dict[str, Any] = {
                "serviceKey": self._settings.tourapi_service_key,
                "MobileOS": "ETC",
                "MobileApp": self._settings.tourapi_mobile_app,
                "_type": "json",
                "numOfRows": num_of_rows,
                "pageNo": page_no,
                "arrange": self._settings.batch_arrange,
            }
            if area_code is not None:
                params["areaCode"] = area_code
            if sigungu_code is not None:
                params["sigunguCode"] = sigungu_code
            if content_type_id is not None:
                params["contentTypeId"] = content_type_id

            payload = self._fetch_page(params)
            items, total_count = _extract_items(payload)
            logger.info(
                "areaBasedList page=%s rows=%s total=%s", page_no, len(items), total_count
            )
            yield from items

            pages_seen += 1
            if max_pages is not None and pages_seen >= max_pages:
                break
            if page_no * num_of_rows >= total_count or not items:
                break
            page_no += 1


def _extract_items(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    """TourAPI 응답 봉투(response.body.items.item)에서 item 리스트/총건수 추출."""
    try:
        body = payload["response"]["body"]
    except (KeyError, TypeError) as exc:
        raise TourApiError(f"예상치 못한 응답 구조: {str(payload)[:200]!r}") from exc

    total_count = int(body.get("totalCount") or 0)
    items_node = body.get("items")
    # 결과 0건이면 items 가 빈 문자열("")로 오는 경우가 있다.
    if not items_node:
        return [], total_count
    item = items_node.get("item", [])
    if isinstance(item, dict):  # 1건이면 dict 로 옴
        item = [item]
    return item, total_count
