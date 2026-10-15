"""Bellwether API on Modal.

Deploy:   cd backend; $env:PYTHONUTF8=1; modal deploy modal_web.py
Data:     volume 'bellwether-web-data' mounted at /data (bellwether.db, companies.csv, investors*.json,
          cache/, raw/logos/). Secrets: 'bellwether-secrets' (API keys, model names).

One container only (max_containers=1): SQLite and the in-process run tasks / SSE streams need it.
"""

from pathlib import Path

import modal

HERE = Path(__file__).resolve().parent
MOCKS = HERE.parent / "frontend" / "src" / "mocks"

volume = modal.Volume.from_name("bellwether-web-data", create_if_missing=True)

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "anthropic>=1.14.0", "fastapi[standard]>=0.143.1", "httpx>=0.28.1", "modal>=1.6.1",
        "pydantic>=2.14.1", "python-dotenv>=1.2.4", "uvicorn>=0.54.0",
    )
    .env({
        "BELLWETHER_DATA_DIR": "/data",
        "BELLWETHER_CACHE_DIR": "/data/cache",
        "BELLWETHER_MOCKS_DIR": "/root/mocks",
        "BELLWETHER_DB": "/data/bellwether.db",
        "COMPANIES_CSV": "/data/companies.csv",
        "DEMO_MODE": "live",
        "RUN_PROFILE": "fast",
        "MODAL_APP": "bellwether",
        "BELLWETHER_IN_MODAL": "1",
    })
    .add_local_dir(MOCKS, "/root/mocks", ignore=["**/*.ts", "**/*.tsx"])
    .add_local_dir(HERE / "app", "/root/app", ignore=["**/__pycache__/**"])
)

app = modal.App("bellwether-web", image=image)


@app.function(
    cpu=4, memory=8192, timeout=3600, min_containers=1, max_containers=1,
    volumes={"/data": volume}, secrets=[modal.Secret.from_name("bellwether-secrets")],
)
@modal.concurrent(max_inputs=100)
@modal.asgi_app()
def web():
    import asyncio
    import logging
    import sys

    sys.path.insert(0, "/root")
    volume.reload()
    from app.main import app as fastapi_app

    log = logging.getLogger("bellwether.volume")

    async def _commit_loop():
        while True:
            await asyncio.sleep(30)
            try:
                await asyncio.to_thread(volume.commit)
            except Exception:
                log.exception("volume commit failed")

    inner = fastapi_app.router.lifespan_context

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(a):
        async with inner(a):
            task = asyncio.create_task(_commit_loop())
            try:
                yield
            finally:
                task.cancel()
                try:
                    volume.commit()
                except Exception:
                    pass

    fastapi_app.router.lifespan_context = lifespan
    return fastapi_app
