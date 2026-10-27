"""Patrón Publicador/Suscriptor.

Bus de eventos en memoria. Los módulos publican hechos del negocio
(SolicitudCreada, DonantesSeleccionados, UnidadRegistrada) sin conocer
quién los consume. En la arquitectura objetivo este bus se reemplaza por
un broker gestionado (RabbitMQ, Amazon SNS/SQS o Google Pub/Sub) sin
cambiar a los publicadores ni a los suscriptores.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

log = logging.getLogger("redvital.eventos")


@dataclass
class Evento:
    tipo: str
    datos: dict[str, Any]
    fecha: datetime = field(default_factory=datetime.now)


Manejador = Callable[[Evento], None]


class BusEventos:
    def __init__(self) -> None:
        self._suscriptores: dict[str, list[Manejador]] = defaultdict(list)
        self.historial: list[Evento] = []

    def suscribir(self, tipo: str, manejador: Manejador) -> None:
        self._suscriptores[tipo].append(manejador)

    def publicar(self, tipo: str, /, **datos: Any) -> Evento:
        evento = Evento(tipo=tipo, datos=datos)
        self.historial.append(evento)
        log.info("Evento publicado: %s", tipo)
        for manejador in list(self._suscriptores[tipo]):
            # Un suscriptor que falla no afecta al publicador ni a los demás
            # suscriptores: así se mantiene el bajo acoplamiento.
            try:
                manejador(evento)
            except Exception:  # noqa: BLE001
                log.exception("Fallo en el suscriptor de %s", tipo)
        return evento

    def ultimos(self, n: int = 20) -> list[Evento]:
        return list(reversed(self.historial[-n:]))
