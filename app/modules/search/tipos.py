"""Tipos publicos del buscador."""

from __future__ import annotations

from enum import StrEnum


class TipoDeContenido(StrEnum):
    POST = "post"
    BOOK_REVIEW = "book_review"
    VIDEO = "video"
    PROJECT = "project"
