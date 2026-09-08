"""Frontera HTTP de seguridad: tambien envuelve errores y preflights."""

from __future__ import annotations

from typing import Any, Final

from fastapi import FastAPI
from starlette.datastructures import MutableHeaders
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.shared.configuration import Settings
from app.shared.errors.handlers import build_error_response, request_id_de
from app.shared.logging.middleware import CorrelacionDePeticiones

# Incluye el sobre multipart. El limite del ARCHIVO sigue siendo 5 MiB en
# dominio; aqui se acota la recepcion antes de que el parser use RAM/disco.
LIMITE_CUERPO_DE_SUBIDA: Final = 5 * 1024 * 1024 + 64 * 1024


class CabecerasDeSeguridad:
    """No depende del codigo de estado ni de que se ejecute un endpoint."""

    def __init__(self, app: ASGIApp, *, prefijo_admin: str) -> None:
        self._app = app
        self._prefijo_admin = prefijo_admin

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        async def enviar(mensaje: Message) -> None:
            if mensaje["type"] == "http.response.start":
                cabeceras = MutableHeaders(scope=mensaje)
                cabeceras["X-Content-Type-Options"] = "nosniff"
                cabeceras["X-Frame-Options"] = "DENY"
                cabeceras["Referrer-Policy"] = "no-referrer"
                cabeceras["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
                ruta = scope.get("path", "")
                # Swagger local carga su propio HTML/CDN. No se aplica una CSP
                # que lo rompa; no es una superficie del sitio ni un DTO del API.
                if ruta != "/docs":
                    cabeceras["Content-Security-Policy"] = (
                        "default-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
                        "form-action 'none'"
                    )
                if ruta != "/sitemap.xml":
                    cabeceras["X-Robots-Tag"] = "noindex, nofollow"
                if ruta == self._prefijo_admin or ruta.startswith(self._prefijo_admin + "/"):
                    cabeceras["Cache-Control"] = "no-store"
            await send(mensaje)

        await self._app(scope, receive, enviar)


class LimiteDeSubida:
    """Recepcion acotada sin fiarse de Content-Length ni dejar spools ilimitados."""

    def __init__(self, app: ASGIApp, *, ruta: str) -> None:
        self._app = app
        self._ruta = ruta

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or scope.get("path", "").rstrip("/") != self._ruta
        ):
            await self._app(scope, receive, send)
            return

        peticion = Request(scope)

        async def rechazar(estado: int) -> None:
            respuesta = build_error_response(
                status_code=estado,
                code="payload_too_large" if estado == 413 else "bad_request",
                message="El cuerpo de la peticion no es valido o supera el limite permitido.",
                request_id=request_id_de(peticion),
            )
            await respuesta(scope, receive, send)

        longitudes = peticion.headers.getlist("content-length")
        if len(longitudes) > 1 or (longitudes and not longitudes[0].isascii()):
            await rechazar(400)
            return
        if longitudes:
            if not longitudes[0].isdigit():
                await rechazar(400)
                return
            # Evita convertir un entero de longitud arbitraria.
            if len(longitudes[0]) > 10 or int(longitudes[0]) > LIMITE_CUERPO_DE_SUBIDA:
                await rechazar(413)
                return

        cuerpo = bytearray()
        while True:
            mensaje = await receive()
            if mensaje["type"] == "http.disconnect":
                return
            fragmento = mensaje.get("body", b"")
            if len(cuerpo) + len(fragmento) > LIMITE_CUERPO_DE_SUBIDA:
                await rechazar(413)
                return
            cuerpo.extend(fragmento)
            if not mensaje.get("more_body", False):
                break

        entregado = False

        async def recibir() -> Message:
            nonlocal entregado
            if entregado:
                return await receive()
            entregado = True
            return {"type": "http.request", "body": bytes(cuerpo), "more_body": False}

        await self._app(scope, recibir, send)


class AplicacionSegura(FastAPI):
    """Orden explicito: correlacion → headers → CORS → limite → FastAPI.

    FastAPI pone ServerErrorMiddleware por encima de add_middleware. Envolver
    build_middleware_stack conserva su API, sus dependencias y su inicializacion
    perezosa, y garantiza cabeceras CORS/seguridad tambien en los 500 no controlados.
    El formatter y el middleware de correlacion aprobados se reutilizan intactos.
    """

    def __init__(self, *, configuracion: Settings, **kwargs: Any) -> None:
        self._configuracion_seguridad = configuracion
        super().__init__(**kwargs)

    def build_middleware_stack(self) -> ASGIApp:
        configuracion = self._configuracion_seguridad
        aplicacion: ASGIApp = LimiteDeSubida(
            super().build_middleware_stack(), ruta=f"{configuracion.auth_cookie_path}/media"
        )
        # La misma lista expresa la politica de origen del panel (D-15).
        # Vacia no habilita lecturas cross-origin. El Compose local funciona
        # same-origin, y no necesita ningun comodin ni origen adicional.
        if configuracion.origenes_administrativos_permitidos:
            aplicacion = CORSMiddleware(
                aplicacion,
                allow_origins=list(configuracion.origenes_administrativos_permitidos),
                allow_credentials=True,
                allow_methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"],
                allow_headers=["Content-Type", "X-Request-ID"],
                expose_headers=["X-Request-ID", "Retry-After"],
                max_age=600,
            )
        return CorrelacionDePeticiones(
            CabecerasDeSeguridad(aplicacion, prefijo_admin=configuracion.auth_cookie_path)
        )
