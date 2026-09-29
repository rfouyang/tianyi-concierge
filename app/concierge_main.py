"""Run the concierge console (LAN) and the public MRT API in one process."""

from __future__ import annotations

import asyncio
import shlex
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from loguru import logger

# Make direct IDE/file execution behave like ``python -m app.concierge_main``.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.api_concierge.api_main import router as api_router  # noqa: E402
from app.api_mrt.router import MrtApiError, mrt_error_response  # noqa: E402
from app.api_mrt.router import router as mrt_router  # noqa: E402
from app.application import ConciergeApplication  # noqa: E402
from app.ui_concierge.ui_main import router as ui_router  # noqa: E402
from config.settings import AppSettings  # noqa: E402
from util.tailwind_asset_helper import TailwindAssetHelper  # noqa: E402

STATIC_DIR = Path(__file__).resolve().parent / "ui_concierge" / "static"
NODE_MODULES = PROJECT_ROOT / "node_modules"
FRONTEND_ASSETS = TailwindAssetHelper.for_concierge(project_root=PROJECT_ROOT)


def create_console_app(application: ConciergeApplication) -> FastAPI:
    """The operator console: pages, REST API, and WebSocket (LAN only)."""

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        FRONTEND_ASSETS.ensure_built()
        yield

    web_app = FastAPI(title="Tianyi Concierge", version="0.1.0", lifespan=lifespan)
    web_app.state.concierge = application
    web_app.mount("/static/concierge", StaticFiles(directory=STATIC_DIR), name="concierge_static")
    web_app.mount(
        "/static/vendor/preline",
        StaticFiles(directory=NODE_MODULES / "preline" / "dist", check_dir=False),
        name="preline",
    )
    web_app.mount(
        "/static/vendor/fonts",
        StaticFiles(
            directory=NODE_MODULES / "@fontsource" / "ibm-plex-sans" / "files", check_dir=False
        ),
        name="fonts",
    )
    web_app.include_router(api_router)
    web_app.include_router(ui_router)
    return web_app


def create_mrt_app(application: ConciergeApplication) -> FastAPI:
    """Only the authenticated MRT API; this is the port ngrok exposes."""
    web_app = FastAPI(title="MRT Intervention API", version="0.1.0", docs_url=None, redoc_url=None)
    web_app.state.concierge = application
    web_app.add_exception_handler(MrtApiError, mrt_error_response)
    web_app.include_router(mrt_router)
    return web_app


def open_ngrok_tunnel(settings: AppSettings) -> str | None:
    """Expose the MRT port publicly; skipped when offline or unconfigured."""
    if not settings.ngrok_api_key:
        logger.info("NGROK_API_KEY is not set; the MRT API is reachable on the LAN only")
        return None
    try:
        import ngrok

        ngrok.set_auth_token(settings.ngrok_api_key)
        public_url = ngrok.forward(settings.mrt_port, proto="http").url()
    except Exception as error:
        logger.warning(f"ngrok is unavailable (offline?); MRT stays LAN-only: {error}")
        return None
    authorization = shlex.quote(f"Authorization: Bearer {settings.mrt_api_key}")
    logger.info(f"MRT public URL: {public_url}")
    for number in range(1, 5):
        url = shlex.quote(f"{public_url}/api/mrt/v1/interventions?action={number}")
        logger.info(f"MRT action {number}: curl -H {authorization} {url}")
    return public_url


async def serve(settings: AppSettings, application: ConciergeApplication) -> None:
    servers = [
        uvicorn.Server(
            uvicorn.Config(
                create_console_app(application),
                host=settings.console_host,
                port=settings.console_port,
                log_level="info",
                access_log=False,
            )
        )
    ]
    if settings.mrt_enabled:
        servers.append(
            uvicorn.Server(
                uvicorn.Config(
                    create_mrt_app(application),
                    host=settings.mrt_host,
                    port=settings.mrt_port,
                    log_level="info",
                    access_log=False,
                )
            )
        )
    else:
        logger.warning("MRT_API_KEY is not set; the MRT API server is disabled")
    await asyncio.gather(*(server.serve() for server in servers))


def configure_logging() -> None:
    """INFO by default; robot polling reads log at DEBUG (set LOG_LEVEL=DEBUG to see them)."""
    import os

    logger.remove()
    logger.add(sys.stderr, level=os.getenv("LOG_LEVEL", "INFO").upper())


def main() -> None:
    configure_logging()
    settings = AppSettings.from_env()
    application = ConciergeApplication.build(settings=settings)
    application.start()
    public_url = open_ngrok_tunnel(settings) if settings.mrt_enabled else None
    logger.info(f"Tianyi Concierge console: http://{settings.console_host}:{settings.console_port}")
    try:
        asyncio.run(serve(settings, application))
    finally:
        application.close()
        if public_url:
            try:
                import ngrok

                ngrok.disconnect(public_url)
            except Exception:
                pass


if __name__ == "__main__":
    main()
