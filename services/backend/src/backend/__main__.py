"""Entrypoint: python -m backend"""

import uvicorn

from .config import settings


def main() -> int:
    uvicorn.run(
        "backend.app:app",
        host="0.0.0.0",
        port=settings.port,
        log_level=settings.log_level,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
