"""Punto de entrada de la aplicación RedVital."""
from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.contenedor import crear_contenedor
from app.gateway.rutas import router
from app.gateway.seguridad import requiere_rol

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

ESTATICOS = Path(__file__).parent / "static"
LIMITE_POR_MINUTO = 240

app = FastAPI(
    title="RedVital API",
    version="1.0.0",
    description="Prototipo académico: plataforma de conexión entre bancos de sangre, hospitales y donantes.",
)
app.state.contenedor = crear_contenedor()
_peticiones: dict[str, deque] = defaultdict(deque)


@app.middleware("http")
async def gateway(request: Request, call_next):
    """Responsabilidades transversales del gateway: límite de tasa, trazabilidad y tiempos."""
    if request.url.path.startswith("/api"):
        ip = request.client.host if request.client else "desconocida"
        ahora = time.monotonic()
        cola = _peticiones[ip]
        while cola and ahora - cola[0] > 60:
            cola.popleft()
        if len(cola) >= LIMITE_POR_MINUTO:
            return JSONResponse({"detail": "Demasiadas peticiones; intente en un minuto"}, status_code=429)
        cola.append(ahora)
    inicio = time.perf_counter()
    respuesta = await call_next(request)
    respuesta.headers["X-Request-ID"] = uuid.uuid4().hex[:12]
    respuesta.headers["X-Tiempo-Respuesta-ms"] = f"{(time.perf_counter() - inicio) * 1000:.1f}"
    return respuesta


app.include_router(router)
app.mount("/static", StaticFiles(directory=ESTATICOS), name="static")


@app.get("/", include_in_schema=False)
def inicio():
    return FileResponse(ESTATICOS / "index.html")


@app.get("/salud", tags=["Operación"])
def salud():
    return {"estado": "ok", "servicio": "RedVital"}


@app.post("/api/demo/reiniciar", tags=["Operación"])
def reiniciar_demo(_u=Depends(requiere_rol("admin"))):
    """Restablece los datos de demostración (útil antes de grabar el video)."""
    app.state.contenedor = crear_contenedor()
    return {"estado": "datos reiniciados"}
