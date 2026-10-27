"""Patrón Circuit Breaker.

Protege las llamadas a un servicio externo poco confiable (la pasarela de
SMS y correo). Tiene tres estados:

* CERRADO: las llamadas pasan normalmente y se cuentan los fallos.
* ABIERTO: tras `umbral_fallos` fallos consecutivos se rechazan las
  llamadas de inmediato durante `tiempo_espera` segundos, sin esperar al
  proveedor caído.
* SEMIABIERTO: vencida la espera se deja pasar una llamada de prueba;
  si funciona el circuito se cierra, si falla vuelve a abrirse.
"""
from __future__ import annotations

import time
from enum import Enum
from typing import Any, Callable


class EstadoCircuito(str, Enum):
    CERRADO = "CERRADO"
    ABIERTO = "ABIERTO"
    SEMIABIERTO = "SEMIABIERTO"


class CircuitoAbiertoError(Exception):
    """Se lanza cuando el circuito rechaza la llamada sin intentarla."""


class CircuitBreaker:
    def __init__(self, umbral_fallos: int = 3, tiempo_espera: float = 30.0,
                 reloj: Callable[[], float] = time.monotonic) -> None:
        self.umbral_fallos = umbral_fallos
        self.tiempo_espera = tiempo_espera
        self._reloj = reloj
        self._estado = EstadoCircuito.CERRADO
        self.fallos_consecutivos = 0
        self._abierto_desde: float | None = None
        self.llamadas_rechazadas = 0

    @property
    def estado(self) -> EstadoCircuito:
        if (self._estado is EstadoCircuito.ABIERTO and self._abierto_desde is not None
                and self._reloj() - self._abierto_desde >= self.tiempo_espera):
            self._estado = EstadoCircuito.SEMIABIERTO
        return self._estado

    def segundos_para_reintento(self) -> float:
        if self.estado is not EstadoCircuito.ABIERTO or self._abierto_desde is None:
            return 0.0
        return max(0.0, self.tiempo_espera - (self._reloj() - self._abierto_desde))

    def ejecutar(self, operacion: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        if self.estado is EstadoCircuito.ABIERTO:
            self.llamadas_rechazadas += 1
            raise CircuitoAbiertoError("Proveedor no disponible; circuito abierto")
        try:
            resultado = operacion(*args, **kwargs)
        except Exception:
            self._registrar_fallo()
            raise
        self._registrar_exito()
        return resultado

    def _registrar_fallo(self) -> None:
        self.fallos_consecutivos += 1
        if (self._estado is EstadoCircuito.SEMIABIERTO
                or self.fallos_consecutivos >= self.umbral_fallos):
            self._estado = EstadoCircuito.ABIERTO
            self._abierto_desde = self._reloj()

    def _registrar_exito(self) -> None:
        self.fallos_consecutivos = 0
        self._estado = EstadoCircuito.CERRADO
        self._abierto_desde = None

    def reiniciar(self) -> None:
        self._registrar_exito()
        self.llamadas_rechazadas = 0
