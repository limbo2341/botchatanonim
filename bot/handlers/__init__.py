from aiogram import Router

from .start import router as start_router
from .search import router as search_router


def setup_routers() -> Router:
    router = Router()

    router.include_router(start_router)
    router.include_router(search_router)

    return router
