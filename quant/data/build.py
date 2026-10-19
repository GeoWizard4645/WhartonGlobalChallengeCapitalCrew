"""Build the whole data cache from scratch (SEC filings, index history, prices, factors). ~15 minutes, ~5 GB.

    .venv/bin/python -m quant.data.build

Steps: download SEC bulk XBRL files -> parse facts and filings -> patch filings missing from the bulk file ->
point-in-time S&P 500/400/600 membership with GICS -> Yahoo prices -> point-in-time fundamentals -> factors.
Every step skips work that is already cached.
"""
from __future__ import annotations

import logging

import requests

from quant import settings

SEC_FILES = {
    "companyfacts.zip": "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip",
    "submissions.zip": "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip",
}


def download_sec(force: bool = False) -> None:
    for name, url in SEC_FILES.items():
        path = settings.SEC_DIR / name
        if path.exists() and not force:
            continue
        with requests.get(url, headers={"User-Agent": settings.SEC_USER_AGENT}, stream=True, timeout=600) as r:
            r.raise_for_status()
            with open(path.with_suffix(".part"), "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
        path.with_suffix(".part").rename(path)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    from quant.data import factors, fundamentals, prices, sec, universe

    download_sec()
    sec.build_all()
    sec.build_fsds_patch()
    universe.build_all()
    prices.download()
    fundamentals.build_snapshots()
    factors.download_all()


if __name__ == "__main__":
    main()
