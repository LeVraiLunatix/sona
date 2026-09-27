"""Lance l'API HTTP privée de Sona (backend de l'app iOS).

Usage : `.venv/bin/python run_api.py`. Nécessite `API_TOKEN` dans `.env` (voir
`.env.example` et la section « API » du README) ; `BOT_TOKEN` n'est pas requis
pour faire tourner l'API seule.
"""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.getenv("API_HOST", "127.0.0.1")
    port = int(os.getenv("API_PORT", "8000"))
    uvicorn.run("app.api.main:app", host=host, port=port)


if __name__ == "__main__":
    main()
