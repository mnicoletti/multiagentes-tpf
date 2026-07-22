"""python -m a2a_compliance — levanta el servicio A2A consultivo."""

from __future__ import annotations

import os

import uvicorn

from a2a_compliance.agent_card import DEFAULT_HOST, DEFAULT_PORT


def main() -> None:
    host = os.environ.get("A2A_HOST", DEFAULT_HOST)
    port = int(os.environ.get("A2A_PORT", str(DEFAULT_PORT)))
    uvicorn.run(
        "a2a_compliance.app:app",
        host=host,
        port=port,
        log_level=os.environ.get("A2A_LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    main()
