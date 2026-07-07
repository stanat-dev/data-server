"""테스트용 env 안전망. engine 은 lazy(app/db.py) 라 import 만으로는 env 가 필요 없지만,
누군가 import 시점 Settings 사용을 다시 넣어도 테스트가 깨지지 않도록 더미를 채워 둔다."""

from __future__ import annotations

import os

os.environ.setdefault("TOURAPI_SERVICE_KEY", "test-dummy-key")
os.environ.setdefault(
    "DATABASE_URL", "mysql+pymysql://test:test@localhost:3306/test?charset=utf8mb4"
)
