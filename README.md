# data-server

stanat **TourAPI 적재 서버** (FastAPI/Python).

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
- upsert 는 `INSERT … ON DUPLICATE KEY UPDATE` → **재실행 idempotent**.ㅍ
## 구조

```
app/
  config.py            # 환경설정 (pydantic-settings, env 주입)
  db.py                # SQLAlchemy 엔진/세션 (TiDB 직접 쓰기)
  models.py            # ExternalPlace ORM (Flyway 스키마와 1:1)
  schemas.py           # NormalizedPlace / IngestRequest / IngestResult
  repository.py        # external_places upsert
  tourapi/
    client.py          # areaBasedList2 페이지 루프 (httpx + tenacity 재시도)
    normalizer.py      # 원본 item → NormalizedPlace (좌표 필터 포함)
  services/ingest.py   # 오케스트레이션: fetch → normalize → upsert
  main.py              # FastAPI 앱 (수동 트리거 + /health)
  cli.py               # 크론/수동 배치 엔트리포인트
tests/
  test_normalizer.py   # mapx→lng/mapy→lat, 좌표 필터, 주소 합성
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

# 1) FastAPI 서버 (수동 트리거)
uvicorn app.main:app --reload
#   POST /ingest/area-based   {"area_code": 1, "content_type_id": 12, "max_pages": 1}
#   GET  /health

# 2) 크론/수동 배치
python -m app.cli --max-pages 1                       # 전국 1페이지
python -m app.cli --area-code 1 --content-type-id 12  # 서울 관광지

# 테스트 (DB/네트워크 불필요 — 정규화 단위테스트)
pytest
```

## 열린 결정 (roadmap §6)

- **트리거**: 수동(`/ingest`) vs 크론 — 둘 다 `services.ingest` 공유, 운영에서 확정.
- **대상 areaCode 범위**, `contentTypeId` 화이트리스트.
- **DB 접근**: 같은 TiDB 직접 쓰기(현재 채택) vs backend write-API 경유 — 바꾸려면 `repository.py` 만 교체.
- **변경추적**: `areaBasedSyncList2` + `external_place_raw_snapshots` 는 **배치 정착 후** 활성화(지금은 YAGNI).
