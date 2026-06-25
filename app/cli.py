
from __future__ import annotations

import argparse
import logging
import sys

from app.schemas import IngestRequest
from app.services.ingest import run_ingest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TourAPI areaBasedList 배치 적재")
    parser.add_argument("--area-code", type=int, default=None)
    parser.add_argument("--sigungu-code", type=int, default=None)
    parser.add_argument("--content-type-id", type=int, default=None)
    parser.add_argument("--max-pages", type=int, default=None)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    req = IngestRequest(
        area_code=args.area_code,
        sigungu_code=args.sigungu_code,
        content_type_id=args.content_type_id,
        max_pages=args.max_pages,
    )
    result = run_ingest(req)
    logging.info(
        "RESULT fetched=%s skipped_no_coords=%s upserted=%s",
        result.fetched,
        result.skipped_no_coords,
        result.upserted,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
