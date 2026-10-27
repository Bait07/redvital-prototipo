"""Módulo de notificaciones.

Se suscribe a DonantesSeleccionados y envía alertas a través de un
proveedor externo protegido por un Circuit Breaker. Si el circuito está
abierto, la alerta queda pendiente de reintento en lugar de bloquear el
flujo o perderse.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from app.core.circuit_breaker import CircuitBreaker, CircuitoAbiertoError
from app.core.dominio import Alerta, Canal, Donante, EstadoAlerta
from app.core.eventos import BusEventos, Evento
from app.modulos.donantes import RepositorioDonantes
from app.modulos.solicitudes import ServicioSolicitudes

log = logging.getLogger("redvital.notificaciones")


class ProveedorMensajeria(ABC):
    @abstractmethod
    def enviar(self, destino: str, mensaje: str) -> None: ...


class ProveedorSimulado(ProveedorMensajeria):
    """Simula una pasarela de SMS y correo. Permite forzar fallas para la demo."""

    def __init__(self) -> None:
        self.falla_activa = False
        self.enviados: list[tuple[str, str]] = []

    def enviar(self, destino: str, mensaje: str) -> None:
        if self.falla_activa:
            raise ConnectionError("La pasarela de mensajería no responde")
        self.enviados.append((destino, mensaje))


class ServicioNotificaciones:
    def __init__(self, bus: BusEventos, proveedor: ProveedorMensajeria,
                 circuito: CircuitBreaker, repo_donantes: RepositorioDonantes,
                 solicitudes: ServicioSolicitudes) -> None:
        self.bus = bus
        self.proveedor = proveedor
        self.circuito = circuito
        self.repo_donantes = repo_donantes
        self.solicitudes = solicitudes
        self.alertas: dict[str, Alerta] = {}
        bus.suscribir("DonantesSeleccionados", self._al_seleccionar_donantes)

    def _al_seleccionar_donantes(self, evento: Evento) -> None:
        for donante_id in evento.datos["donantes"]:
            donante = self.repo_donantes.por_id(donante_id)
            if donante:
                alerta = Alerta(solicitud_id=evento.datos["solicitud_id"], donante_id=donante.id,
                                canal=donante.canal, estado=EstadoAlerta.PENDIENTE_REINTENTO)
                self.alertas[alerta.id] = alerta
                self._intentar_envio(alerta, donante)

    def _intentar_envio(self, alerta: Alerta, donante: Donante) -> None:
        destino = donante.telefono if donante.canal is Canal.SMS else donante.correo
        mensaje = (f"RedVital: se necesita sangre {donante.tipo.value} con urgencia. "
                   f"Responda en el enlace de la alerta {alerta.id}.")
        try:
            self.circuito.ejecutar(self.proveedor.enviar, destino, mensaje)
            alerta.estado = EstadoAlerta.ENVIADA
            alerta.detalle = f"Enviada por {alerta.canal.value}"
        except CircuitoAbiertoError:
            alerta.estado = EstadoAlerta.PENDIENTE_REINTENTO
            alerta.detalle = "Circuito abierto: rechazo rápido, en cola de reintento"
        except Exception as error:  # noqa: BLE001
            alerta.estado = EstadoAlerta.PENDIENTE_REINTENTO
            alerta.detalle = f"Fallo del proveedor: {error}"
            log.warning("Fallo al enviar alerta %s: %s", alerta.id, error)

    def reintentar_pendientes(self) -> int:
        enviadas = 0
        for alerta in self.alertas.values():
            if alerta.estado is EstadoAlerta.PENDIENTE_REINTENTO:
                donante = self.repo_donantes.por_id(alerta.donante_id)
                if donante:
                    self._intentar_envio(alerta, donante)
                    enviadas += alerta.estado is EstadoAlerta.ENVIADA
        return enviadas

    def responder(self, alerta_id: str, acepta: bool) -> Alerta:
        alerta = self.alertas.get(alerta_id)
        if alerta is None:
            raise KeyError("Alerta no encontrada")
        if alerta.estado in (EstadoAlerta.ACEPTADA, EstadoAlerta.RECHAZADA):
            raise ValueError("La alerta ya fue respondida")
        alerta.estado = EstadoAlerta.ACEPTADA if acepta else EstadoAlerta.RECHAZADA
        alerta.detalle = "El donante confirmó que asistirá" if acepta else "El donante no puede asistir"
        if acepta:
            self.solicitudes.registrar_compromiso(alerta.solicitud_id)
        self.bus.publicar("AlertaRespondida", alerta_id=alerta.id, acepta=acepta)
        return alerta

    def tasa_respuesta(self) -> float:
        respondidas = [a for a in self.alertas.values()
                       if a.estado in (EstadoAlerta.ACEPTADA, EstadoAlerta.RECHAZADA)]
        enviadas = [a for a in self.alertas.values() if a.estado is not EstadoAlerta.PENDIENTE_REINTENTO]
        return round(len(respondidas) / len(enviadas) * 100, 1) if enviadas else 0.0
