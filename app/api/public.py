"""Montaje incremental de los routers publicos de contenido.

La base validada de la remediacion empieza exclusivamente con Posts. Cada
router adicional se incorpora solo despues de que su slice haya registrado un
RED verificable y haya alcanzado GREEN.
"""

from __future__ import annotations

from typing import Final

from fastapi import APIRouter

from app.modules.book_reviews.presentation import router as book_reviews_router
from app.modules.posts.presentation import router as posts_router
from app.modules.profile.presentation import router as profile_router
from app.modules.projects.presentation import router as projects_router
from app.modules.search.presentation import router as search_router
from app.modules.tags.presentation import router as tags_router
from app.modules.videos.presentation import router as videos_router

routers_publicos: Final[tuple[APIRouter, ...]] = (
    posts_router,
    profile_router,
    book_reviews_router,
    videos_router,
    projects_router,
    tags_router,
    search_router,
)

__all__ = ["routers_publicos"]
