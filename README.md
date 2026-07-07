# data-server

stanat **TourAPI 적재 + 경로 생성 서버** (FastAPI/Python).

두 트랙은 코드에서 분리되어 있다:

| 트랙 | 진입점 | 코드 | env 의존 |
|---|---|---|---|
| **경로 생성** | `POST /routes/generate` | `services/route_generator.py` (+ `schemas.py` Route*) | 없음 (DB/TourAPI 미접근) |
| **배치 적재** | `POST /ingest/area-based`, `python -m app.cli` | `services/ingest.py`, `tourapi/`, `repository.py`, `models.py`, `db.py` | `TOURAPI_SERVICE_KEY`, `DATABASE_URL` |

DB engine 은 첫 사용 시점에 생성(lazy, `db.py`)되므로 경로 생성만 쓰는 프로세스는 env 없이도 뜬다.

## TourAPI 엔드포인트 (KorService2)

- **데이터셋**: [15101578 한국관광공사_국문 관광정보 서비스_GW](https://www.data.go.kr/data/15101578/openapi.do) (= KorService2). 이 페이지에서 **활용신청** 후 서비스키 발급.
- **베이스**: `https://apis.data.go.kr/B551011/KorService2`

## 정규화 매핑 (areaBasedList2 → external_places)

| TourAPI | 컬럼 | 비고 |
|---|---|---|
| `contentid` | `source_content_id` | |
| `title` | `name` | |
| `addr1` (+`addr2`) | `address` | 공백으로 합성 |
| `mapx` | `lng` (경도) | ⚠️ **mapx=경도/mapy=위도, 뒤바꾸지 말 것** |
| `mapy` | `lat` (위도) | |
| `tel` | `tel` | |
| `firstimage` | `image_url` | |
| — | `overview` | areaBasedList2 미제공 → `NULL` (나중에 `detailCommon2` 보강) |
| (고정) | `source=TOURAPI`, `language=KO` | |

- 좌표(`mapx`/`mapy`)가 없거나 `0` 이면 **제외**(`lat`/`lng` NOT NULL).
- upsert 는 `INSERT … ON DUPLICATE KEY UPDATE` → **재실행 idempotent**.

## 경로 생성 API — `POST /routes/generate`

backend-spring 이 호출하는 **stateless 순수 함수**(요청 payload 만 사용, DB 미접근).
`ref` 는 backend-spring 소유의 불투명 문자열로 그대로 반환된다(passthrough).
알고리즘 교체 지점은 `app/services/route_generator.py` 의 `generate_route()` 하나.

```jsonc
// Request
{
  "day_count": 2,                       // 1~30
  "places": [                           // 1개 이상
    { "ref": "EXTERNAL_PLACE:5",  "lat": 37.5796, "lng": 126.9770, "stay_minutes": 60 },
    { "ref": "SACRED_PLACE:101", "lat": 37.5563, "lng": 126.9236, "stay_minutes": 90 }
  ]
}
// Response 200
{
  "algorithm_version": "distance-v1",
  "days": [
    { "day_no": 1, "items": [
      { "ref": "EXTERNAL_PLACE:5",  "sequence_no": 1, "distance_meter_from_prev": null, "move_minutes_from_prev": null },
      { "ref": "SACRED_PLACE:101", "sequence_no": 2, "distance_meter_from_prev": 4970, "move_minutes_from_prev": 74 }
    ] }
  ]
}
```

**distance-v1 의미론**: `places[0]` 에서 시작하는 haversine nearest-neighbor 순서화 →
`day_count` 개 연속 구간 분할(나머지는 앞 일자 우선, 장소<일수면 빈 `items`) /
`sequence_no` 는 일자별 1부터 / 각 일자 첫 항목의 거리·이동시간은 `null` /
`move_minutes_from_prev = max(1, round(distance/67))` (도보 4km/h).
검증 위반은 422. wire format 의 정본은 `tests/test_routes_api.py`.

## 구조

```
app/
  config.py            # 환경설정 (pydantic-settings, env 주입)
  db.py                # SQLAlchemy 엔진/세션 (TiDB 직접 쓰기)
  models.py            # ExternalPlace ORM (Flyway 스키마와 1:1)
  schemas.py           # NormalizedPlace / Ingest* / RouteGenerate* 모델
  repository.py        # external_places upsert
  tourapi/
    client.py          # areaBasedList2 페이지 루프 (httpx + tenacity 재시도)
    normalizer.py      # 원본 item → NormalizedPlace (좌표 필터 포함)
  services/
    ingest.py          # 오케스트레이션: fetch → normalize → upsert
    route_generator.py # 경로 생성 distance-v1 (교체 지점: generate_route)
  main.py              # FastAPI 앱 (수동 트리거 + /routes/generate + /health)
  cli.py               # 크론/수동 배치 엔트리포인트
tests/
  test_normalizer.py       # mapx→lng/mapy→lat, 좌표 필터, 주소 합성
  test_route_generator.py  # NN 순서/일자 분할/sequence/첫 항목 null
  test_routes_api.py       # /routes/generate wire format 계약(정본)
  fixtures/area_based_list_sample.json
```

## 설정

```bash
cp .env-example .env
# .env 에 TOURAPI_SERVICE_KEY, DATABASE_URL 채우기
```

| env | 설명 |
|---|---|
| `TOURAPI_SERVICE_KEY` | 공공데이터포털 발급 서비스키(Decoding 키 권장) |
| `TOURAPI_BASE_URL` | 기본 `https://apis.data.go.kr/B551011/KorService2` |
| `TOURAPI_AREA_BASED_OP` | 기본 `areaBasedList2` |
| `DATABASE_URL` | TiDB(MySQL 호환). `mysql+pymysql://user:pass@host:4000/stanat?charset=utf8mb4` |
| `BATCH_NUM_OF_ROWS` / `BATCH_MAX_PAGES` / `BATCH_ARRANGE` | 배치 페이징/정렬 |

## 실행

```bash
# 의존성 (Python 3.11+ 권장)
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 1) FastAPI 서버
uvicorn app.main:app --reload
#   POST /ingest/area-based   {"area_code": 1, "content_type_id": 12, "max_pages": 1}
#   POST /routes/generate     (위 '경로 생성 API' 섹션 참고)
#   GET  /health

# 2) 크론/수동 배치
python -m app.cli --max-pages 1                       # 전국 1페이지
python -m app.cli --area-code 1 --content-type-id 12  # 서울 관광지

# 테스트 (DB/네트워크 불필요)
pytest
```

## 로깅

원칙의 정본은 backend-spring `docs/conventions/logging.md` 를 따른다
(레벨 정책, 요약 카운트만·본문 덤프 금지, **TourAPI 키 절대 로그 금지**).

운영에서 보게 되는 로그 (`docker compose logs -f data-server`):

| 레벨 | 이벤트 | 예 |
|---|---|---|
| INFO | 경로 생성 완료 요약 | `route generate done day_count=2 places=8 algorithm=distance-v1 elapsed_ms=1` |
| INFO | 적재 시작/완료 요약 | `ingest start area_code=1 …` / `ingest done fetched=100 skipped=3 upserted=97 elapsed_ms=4210` |
| INFO | TourAPI 페이지 진행 | `areaBasedList page=2 rows=100 total=1873` |
| WARN | TourAPI 재시도 | `TourAPI 재시도 attempt=2 wait=1.0s cause=ConnectTimeout` |
| ERROR | 처리 안 된 예외(500) | uvicorn 이 스택과 함께 출력 |

주의: httpx 예외 메시지에는 serviceKey 포함 URL 이 들어갈 수 있어, 재시도 로그는 예외
**타입명만** 남기고 HTTP 오류는 상태코드+본문 스니펫으로 변환한다(`tourapi/client.py`).

