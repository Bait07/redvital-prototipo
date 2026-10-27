"""Módulo de inventario: unidades de sangre, vencimientos y reservas."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections import Counter
from datetime import date, timedelta

from app.core.dominio import (Componente, Donante, EstadoUnidad, TipoSanguineo,
                              UnidadSangre)
from app.core.eventos import BusEventos
from app.modulos.donantes import ServicioDonantes

# Vida útil de referencia por componente, en días (parametrizable).
VIDA_UTIL_DIAS = {
    Componente.GLOBULOS_ROJOS: 42,
    Componente.PLAQUETAS: 5,
    Componente.PLASMA: 365,
}


class RepositorioInventario(ABC):
    @abstractmethod
    def guardar(self, unidad: UnidadSangre) -> None: ...

    @abstractmethod
    def disponibles(self, tipos: list[TipoSanguineo], componente: Componente) -> list[UnidadSangre]: ...

    @abstractmethod
    def todas(self) -> list[UnidadSangre]: ...


class RepositorioInventarioMemoria(RepositorioInventario):
    def __init__(self) -> None:
        self._datos: dict[str, UnidadSangre] = {}

    def guardar(self, unidad: UnidadSangre) -> None:
        self._datos[unidad.codigo] = unidad

    def disponibles(self, tipos: list[TipoSanguineo], componente: Componente) -> list[UnidadSangre]:
        return [u for u in self._datos.values()
                if u.estado is EstadoUnidad.DISPONIBLE and u.tipo in tipos and u.componente is componente]

    def todas(self) -> list[UnidadSangre]:
        return list(self._datos.values())


class DonanteNoElegibleError(Exception):
    pass


class ServicioInventario:
    def __init__(self, repo: RepositorioInventario, donantes: ServicioDonantes,
                 bus: BusEventos) -> None:
        self.repo = repo
        self.donantes = donantes
        self.bus = bus

    def registrar_donacion(self, donante: Donante, sede_id: str, componente: Componente,
                           hoy: date | None = None) -> UnidadSangre:
        hoy = hoy or date.today()
        resultado = self.donantes.evaluar(donante, hoy)
        if not resultado.elegible:
            raise DonanteNoElegibleError(" ".join(resultado.motivos))
        unidad = UnidadSangre(tipo=donante.tipo, componente=componente, sede_id=sede_id,
                              fecha_extraccion=hoy,
                              fecha_vencimiento=hoy + timedelta(days=VIDA_UTIL_DIAS[componente]))
        self.repo.guardar(unidad)
        self.donantes.registrar_donacion(donante, hoy)
        self.bus.publicar("UnidadRegistrada", codigo=unidad.codigo, tipo=unidad.tipo.value,
                          componente=unidad.componente.value)
        return unidad

    def reservar(self, unidades: list[UnidadSangre], solicitud_id: str) -> None:
        for unidad in unidades:
            unidad.estado = EstadoUnidad.RESERVADA
            unidad.solicitud_id = solicitud_id
            self.repo.guardar(unidad)
        if unidades:
            self.bus.publicar("InventarioActualizado", reservadas=len(unidades), solicitud_id=solicitud_id)

    def marcar_vencidas(self, hoy: date | None = None) -> int:
        hoy = hoy or date.today()
        vencidas = 0
        for unidad in self.repo.todas():
            if unidad.estado is EstadoUnidad.DISPONIBLE and unidad.esta_vencida(hoy):
                unidad.estado = EstadoUnidad.VENCIDA
                self.repo.guardar(unidad)
                vencidas += 1
        if vencidas:
            self.bus.publicar("InventarioActualizado", vencidas=vencidas)
        return vencidas

    def resumen_disponible(self) -> dict[str, int]:
        conteo = Counter(u.tipo.value for u in self.repo.todas()
                         if u.estado is EstadoUnidad.DISPONIBLE
                         and u.componente is Componente.GLOBULOS_ROJOS)
        return {t.value: conteo.get(t.value, 0) for t in TipoSanguineo}
