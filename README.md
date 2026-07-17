# Data-server

stanat **TourAPI 적재 + 경로 생성 서버** (FastAPI/Python).

두 트랙은 코드에서 분리되어 있다:

| 트랙 | 진입점 | 코드 | env 의존 |
|---|---|---|---|
| **경로 생성** | `POST /routes/generate` | `services/route_generator_v2.py` (기본) / `route_generator.py` (v1 핀) (+ `schemas.py` Route*) | 없음 (DB/TourAPI 미접근) |
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
`algorithm` 미지정 시 **distance-v2** 가 기본이고, `"distance-v1"` 으로 요청 단위 롤백할 수 있다.

```jsonc
// Request (algorithm/item_type 은 optional — 구버전 요청도 그대로 동작)
{
  "day_count": 2,                       // 1~30
  "algorithm": null,                    // null=distance-v2 | "distance-v1" 핀
  "places": [                           // 1개 이상
    { "ref": "EXTERNAL_PLACE:5",  "lat": 37.5796, "lng": 126.9770, "stay_minutes": 60, "item_type": "RESTAURANT" },
    { "ref": "SACRED_PLACE:101", "lat": 37.5563, "lng": 126.9236, "stay_minutes": 90, "item_type": "SACRED" }
  ]
}
// Response 200 (day_load_minutes/over_budget/suggested_day_count 는 v2 additive —
//               v1 핀 응답에는 아예 나타나지 않는다. suggested 는 초과 시에만)
{
  "algorithm_version": "distance-v2",
  "days": [
    { "day_no": 1, "day_load_minutes": 233, "over_budget": false, "items": [
      { "ref": "EXTERNAL_PLACE:5",  "sequence_no": 1, "distance_meter_from_prev": null, "move_minutes_from_prev": null },
      { "ref": "SACRED_PLACE:101", "sequence_no": 2, "distance_meter_from_prev": 4970, "move_minutes_from_prev": 30 }
    ] }
  ]
}
```

**distance-v2 의미론** (`app/services/route_generator_v2.py`, 전부 stdlib·결정적·RNG 없음):
1. **felt-cost** `min(도보 d/67, 대중교통 10 + d/250)` 분 — 장거리 구간을 도보로 계산하던 v1 왜곡 수정. `move_minutes_from_prev` 는 felt 기준(최소 1), `distance_meter_from_prev` 는 haversine 미터 그대로.
2. multi-start NN → **2-opt/or-opt** 수렴(일자 경로 자기교차 0) → **split-DP** 로 max(일자 부하) 최소 분할 — 부하 = Σ체류(타입별 기본: SACRED 90/RESTAURANT 60/CAFE 40/ACCOMMODATION 0/기타 60) + Σ이동.
3. 일자 내 ≤10곳은 Held-Karp **정확해**, 초과는 2-opt.
4. `item_type` 이 하나라도 있으면 **사전식 규칙 패스**: P0 숙소 마지막 → P1 점심 식당 11:00–14:00 도착(09:30 시작 가정)·25분+ 구간 회피 → P2 앵커 성지 후반 배치·저녁 식당 → 이동합 → P3 카페 오후 창. 상위 티어를 악화시키는 이동은 수락하지 않는다.
5. 총부하 > `day_count`×600분이면 `suggested_day_count` 로 권장 일수 역제안.

**distance-v1 의미론**(핀 시): `places[0]` 시작 nearest-neighbor → 연속 등분 분할 /
`move_minutes = max(1, round(d/67))` (도보 4km/h). v1 모듈은 동결 상태로 유지된다.

공통: `sequence_no` 는 일자별 1부터, 각 일자 첫 항목의 거리·이동시간은 `null`,
장소<일수면 빈 `items`. 검증 위반은 422. wire format 의 정본은
`tests/test_routes_api.py` + `tests/test_route_v2_contract.py`.

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
    ingest.py              # 오케스트레이션: fetch → normalize → upsert
    route_generator.py     # 경로 생성 distance-v1 (동결 — v1 핀 전용)
    route_generator_v2.py  # 경로 생성 distance-v2 (기본. felt-cost/2-opt/split-DP/규칙 패스)
  main.py              # FastAPI 앱 (수동 트리거 + /routes/generate 디스패치 + /health)
  cli.py               # 크론/수동 배치 엔트리포인트
tests/
  test_normalizer.py         # mapx→lng/mapy→lat, 좌표 필터, 주소 합성
  test_route_generator.py    # v1: NN 순서/일자 분할/sequence/첫 항목 null
  test_route_generator_v2.py # v2 단위: felt/HK 최적성/split 균형/규칙/결정성
  test_routes_api.py         # /routes/generate wire format 계약(정본)
  test_route_v2_contract.py  # v2 wire: 디스패치/열화입력/byte-equal/perf tripwire
  test_route_v2_quality.py   # v2 품질: v1 대비 felt/자기교차 0/부하 균형
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
| `ROUTE_SHADOW_COMPARE` | `1`/`true` 면 v2 응답 시 v1 도 병행 실행해 요약 비교 로그 1줄 (기본 off) |

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
| INFO | 경로 생성 완료 요약 | `route generate done day_count=2 places=8 algorithm=distance-v2 elapsed_ms=3` |
| INFO | 섀도 비교 (`ROUTE_SHADOW_COMPARE=1`) | `route shadow compare places=8 day_count=2 v1_dist_m=… v2_dist_m=… v2_max_load=…` |
| INFO | 적재 시작/완료 요약 | `ingest start area_code=1 …` / `ingest done fetched=100 skipped=3 upserted=97 elapsed_ms=4210` |
| INFO | TourAPI 페이지 진행 | `areaBasedList page=2 rows=100 total=1873` |
| WARN | TourAPI 재시도 | `TourAPI 재시도 attempt=2 wait=1.0s cause=ConnectTimeout` |
| ERROR | 처리 안 된 예외(500) | uvicorn 이 스택과 함께 출력 |

주의: httpx 예외 메시지에는 serviceKey 포함 URL 이 들어갈 수 있어, 재시도 로그는 예외
**타입명만** 남기고 HTTP 오류는 상태코드+본문 스니펫으로 변환한다(`tourapi/client.py`).

