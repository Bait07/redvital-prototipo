"""Módulo de emparejamiento.

* Strategy: la regla de compatibilidad cambia según el componente
  (glóbulos rojos y plaquetas siguen la compatibilidad ABO/Rh del
  receptor; el plasma sigue la regla inversa).
* Cache Aside: la consulta de inventario disponible pasa por la caché.
* Publicador/Suscriptor: reacciona a SolicitudCreada y UnidadRegistrada,
  y publica DonantesSeleccionados.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from app.core.cache import CacheTTL
from app.core.dominio import (Componente, Donante, EstadoSolicitud, Hospital,
                              SolicitudUrgente, TipoSanguineo as T, UnidadSangre,
                              distancia_km)
from app.core.eventos import BusEventos, Evento
from app.modulos.donantes import RepositorioDonantes, ServicioDonantes
from app.modulos.inventario import ServicioInventario
from app.modulos.solicitudes import ServicioSolicitudes


class ReglaCompatibilidad(ABC):
    @abstractmethod
    def donantes_compatibles(self, receptor: T) -> list[T]: ...


class ReglaGlobulosRojos(ReglaCompatibilidad):
    _TABLA = {
        T.O_NEG: [T.O_NEG],
        T.O_POS: [T.O_POS, T.O_NEG],
        T.A_NEG: [T.A_NEG, T.O_NEG],
        T.A_POS: [T.A_POS, T.A_NEG, T.O_POS, T.O_NEG],
        T.B_NEG: [T.B_NEG, T.O_NEG],
        T.B_POS: [T.B_POS, T.B_NEG, T.O_POS, T.O_NEG],
        T.AB_NEG: [T.AB_NEG, T.A_NEG, T.B_NEG, T.O_NEG],
        T.AB_POS: list(T),
    }

    def donantes_compatibles(self, receptor: T) -> list[T]:
        return list(self._TABLA[receptor])


class ReglaPlasma(ReglaCompatibilidad):
    """En plasma la compatibilidad se invierte: AB es el donante universal."""
    _GRUPOS = {"O": ["O", "A", "B", "AB"], "A": ["A", "AB"], "B": ["B", "AB"], "AB": ["AB"]}

    def donantes_compatibles(self, receptor: T) -> list[T]:
        grupo = receptor.value.rstrip("+-")
        return [t for t in T if t.value.rstrip("+-") in self._GRUPOS[grupo]]


REGLAS: dict[Componente, ReglaCompatibilidad] = {
    Componente.GLOBULOS_ROJOS: ReglaGlobulosRojos(),
    Componente.PLAQUETAS: ReglaGlobulosRojos(),
    Componente.PLASMA: ReglaPlasma(),
}


class ServicioEmparejamiento:
    DONANTES_POR_UNIDAD = 3  # se alerta a más donantes de los necesarios

    def __init__(self, bus: BusEventos, cache: CacheTTL, solicitudes: ServicioSolicitudes,
                 inventario: ServicioInventario, donantes: ServicioDonantes,
                 repo_donantes: RepositorioDonantes, hospitales: dict[str, Hospital]) -> None:
        self.bus = bus
        self.cache = cache
        self.solicitudes = solicitudes
        self.inventario = inventario
        self.donantes = donantes
        self.repo_donantes = repo_donantes
        self.hospitales = hospitales
        bus.suscribir("SolicitudCreada", self._al_crear_solicitud)
        bus.suscribir("UnidadRegistrada", self._al_registrar_unidad)
        bus.suscribir("InventarioActualizado", lambda _e: self.cache.invalidar("inventario:"))

    # Cache Aside sobre el inventario disponible
    def _disponibles(self, tipos: list[T], componente: Componente) -> list[UnidadSangre]:
        clave = "inventario:" + componente.name + ":" + ",".join(sorted(t.value for t in tipos))
        return self.cache.obtener_o_cargar(
            clave, lambda: self.inventario.repo.disponibles(tipos, componente))

    def emparejar(self, solicitud: SolicitudUrgente) -> dict:
        regla = REGLAS[solicitud.componente]
        tipos = regla.donantes_compatibles(solicitud.tipo_receptor)
        candidatas = [u for u in self._disponibles(tipos, solicitud.componente)
                      if u.estado.value == "DISPONIBLE"]
        # Primero las que vencen antes, para reducir pérdidas por vencimiento.
        candidatas.sort(key=lambda u: u.fecha_vencimiento)
        a_reservar = candidatas[: solicitud.unidades_pendientes()]
        self.inventario.reservar(a_reservar, solicitud.id)
        self.solicitudes.registrar_reserva(solicitud, len(a_reservar))

        seleccionados: list[Donante] = []
        faltantes = solicitud.unidades_pendientes()
        if faltantes:
            seleccionados = self._seleccionar_donantes(solicitud, tipos, faltantes)
            if seleccionados:
                self.bus.publicar("DonantesSeleccionados", solicitud_id=solicitud.id,
                                  donantes=[d.id for d in seleccionados])
        return {
            "tipos_compatibles": [t.value for t in tipos],
            "unidades_reservadas": len(a_reservar),
            "unidades_faltantes": faltantes,
            "donantes_alertados": len(seleccionados),
        }

    def _seleccionar_donantes(self, solicitud: SolicitudUrgente, tipos: list[T],
                              faltantes: int) -> list[Donante]:
        hoy = date.today()
        hospital = self.hospitales.get(solicitud.hospital_id)
        elegibles = [d for d in self.repo_donantes.buscar_por_tipos(tipos)
                     if self.donantes.evaluar(d, hoy).elegible]
        if hospital:
            elegibles.sort(key=lambda d: distancia_km(d.latitud, d.longitud,
                                                      hospital.latitud, hospital.longitud))
        return elegibles[: faltantes * self.DONANTES_POR_UNIDAD]

    def _al_crear_solicitud(self, evento: Evento) -> None:
        solicitud = self.solicitudes.repo.por_id(evento.datos["solicitud_id"])
        if solicitud:
            self.emparejar(solicitud)

    def _al_registrar_unidad(self, evento: Evento) -> None:
        """Una unidad nueva se asigna a la solicitud abierta más antigua que la necesite."""
        self.cache.invalidar("inventario:")
        tipo, componente = T(evento.datos["tipo"]), Componente(evento.datos["componente"])
        abiertas = sorted((s for s in self.solicitudes.activas()
                           if s.componente is componente and s.estado is not EstadoSolicitud.CUBIERTA),
                          key=lambda s: s.fecha_creacion)
        for solicitud in abiertas:
            if tipo in REGLAS[componente].donantes_compatibles(solicitud.tipo_receptor):
                unidad = next(u for u in self.inventario.repo.todas() if u.codigo == evento.datos["codigo"])
                self.inventario.reservar([unidad], solicitud.id)
                self.solicitudes.registrar_reserva(solicitud, 1)
                break
