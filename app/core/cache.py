"""Patrón Cache Aside.

La aplicación consulta primero la caché; si el dato no está (o venció),
lo lee de la fuente de datos y lo guarda en la caché. Las escrituras
invalidan la entrada afectada. En la arquitectura objetivo esta clase se
reemplaza por Redis.
"""
from __future__ import annotations

import time
from typing import Any, Callable


class CacheTTL:
    def __init__(self, ttl_segundos: float = 30.0,
                 reloj: Callable[[], float] = time.monotonic) -> None:
        self.ttl = ttl_segundos
        self._reloj = reloj
        self._datos: dict[str, tuple[float, Any]] = {}
        self.aciertos = 0
        self.fallos = 0

    def obtener_o_cargar(self, clave: str, cargar: Callable[[], Any]) -> Any:
        entrada = self._datos.get(clave)
        if entrada and self._reloj() - entrada[0] < self.ttl:
            self.aciertos += 1
            return entrada[1]
        self.fallos += 1
        valor = cargar()
        self._datos[clave] = (self._reloj(), valor)
        return valor

    def invalidar(self, prefijo: str = "") -> None:
        for clave in [c for c in self._datos if c.startswith(prefijo)]:
            del self._datos[clave]

    def estadisticas(self) -> dict[str, Any]:
        total = self.aciertos + self.fallos
        return {
            "aciertos": self.aciertos,
            "fallos": self.fallos,
            "tasa_aciertos": round(self.aciertos / total * 100, 1) if total else 0.0,
            "entradas": len(self._datos),
        }
