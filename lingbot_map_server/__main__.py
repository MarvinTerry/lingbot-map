from __future__ import annotations

import os

import uvicorn

from lingbot_map_server.config import load_dotenv_files


def main() -> None:
    load_dotenv_files()
    host = os.getenv("LINGBOT_MAP_SERVER_HOST", "0.0.0.0")
    port = int(os.getenv("LINGBOT_MAP_SERVER_PORT", "8000"))
    uvicorn.run("lingbot_map_server.app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
