"""Standalone trusted worker CLI runner for durable merchant import jobs (#257)."""

from __future__ import annotations

import asyncio
import logging

from sqlmodel import Session

from app.database import operations_engine
from app.import_scheduler import ImportWorker, assert_trusted_worker_environment


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s",
    )
    assert_trusted_worker_environment()
    worker = ImportWorker(lambda: Session(operations_engine))
    asyncio.run(worker.run_forever(install_signals=True))


if __name__ == "__main__":
    main()
