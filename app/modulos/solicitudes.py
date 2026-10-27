"""Módulo de solicitudes urgentes publicadas por hospitales."""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.core.dominio import EstadoSolicitud, SolicitudUrgente
from app.core.eventos import BusEventos


class RepositorioSolicitudes(ABC):
    @abstractmethod
    def guardar(self, solicitud: SolicitudUrgente) -> None: ...

    @abstractmethod
    def por_id(self, solicitud_id: str) -> SolicitudUrgente | None: ...

    @abstractmethod
    def todas(self) -> list[SolicitudUrgente]: ...


class RepositorioSolicitudesMemoria(RepositorioSolicitudes):
    def __init__(self) -> None:
        self._datos: dict[str, SolicitudUrgente] = {}

    def guardar(self, solicitud: SolicitudUrgente) -> None:
        self._datos[solicitud.id] = solicitud

    def por_id(self, solicitud_id: str) -> SolicitudUrgente | None:
        return self._datos.get(solicitud_id)

    def todas(self) -> list[SolicitudUrgente]:
        return sorted(self._datos.values(), key=lambda s: s.fecha_creacion, reverse=True)


class ServicioSolicitudes:
    def __init__(self, repo: RepositorioSolicitudes, bus: BusEventos) -> None:
        self.repo = repo
        self.bus = bus

    def crear(self, solicitud: SolicitudUrgente) -> SolicitudUrgente:
        if solicitud.unidades_requeridas < 1:
            raise ValueError("La solicitud debe requerir al menos una unidad.")
        self.repo.guardar(solicitud)
        # La respuesta al hospital no espera el emparejamiento: se publica un
        # evento y el resto del flujo ocurre en los suscriptores.
        self.bus.publicar("SolicitudCreada", solicitud_id=solicitud.id)
        return solicitud

    def registrar_reserva(self, solicitud: SolicitudUrgente, unidades: int) -> None:
        solicitud.unidades_reservadas += unidades
        solicitud.estado = (EstadoSolicitud.CUBIERTA if solicitud.unidades_pendientes() == 0
                            else EstadoSolicitud.EN_ATENCION)
        self.repo.guardar(solicitud)

    def registrar_compromiso(self, solicitud_id: str) -> None:
        solicitud = self.repo.por_id(solicitud_id)
        if solicitud:
            solicitud.donantes_comprometidos += 1
            self.repo.guardar(solicitud)

    def activas(self) -> list[SolicitudUrgente]:
        return [s for s in self.repo.todas() if s.estado is not EstadoSolicitud.CUBIERTA]
