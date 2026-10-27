"""Módulo de donantes: registro y evaluación de elegibilidad.

Aplica el patrón Repository: el servicio depende de la interfaz
`RepositorioDonantes`, no de la tecnología de almacenamiento.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date

from app.core.dominio import Donante, TipoSanguineo
from app.core.eventos import BusEventos


class RepositorioDonantes(ABC):
    @abstractmethod
    def guardar(self, donante: Donante) -> None: ...

    @abstractmethod
    def por_documento(self, documento: str) -> Donante | None: ...

    @abstractmethod
    def por_id(self, donante_id: str) -> Donante | None: ...

    @abstractmethod
    def buscar_por_tipos(self, tipos: list[TipoSanguineo]) -> list[Donante]: ...

    @abstractmethod
    def todos(self) -> list[Donante]: ...


class RepositorioDonantesMemoria(RepositorioDonantes):
    """Implementación en memoria para el prototipo (reemplazable por PostgreSQL)."""

    def __init__(self) -> None:
        self._datos: dict[str, Donante] = {}

    def guardar(self, donante: Donante) -> None:
        self._datos[donante.documento] = donante

    def por_documento(self, documento: str) -> Donante | None:
        return self._datos.get(documento)

    def por_id(self, donante_id: str) -> Donante | None:
        return next((d for d in self._datos.values() if d.id == donante_id), None)

    def buscar_por_tipos(self, tipos: list[TipoSanguineo]) -> list[Donante]:
        return [d for d in self._datos.values() if d.tipo in tipos]

    def todos(self) -> list[Donante]:
        return list(self._datos.values())


@dataclass
class ParametrosElegibilidad:
    """Parámetros configurables; deben ajustarse a la normativa vigente."""
    edad_minima: int = 18
    edad_maxima: int = 65
    peso_minimo_kg: float = 50.0
    intervalo_minimo_dias: int = 90


@dataclass
class ResultadoElegibilidad:
    elegible: bool
    motivos: list[str]


class DonanteDuplicadoError(Exception):
    pass


class ServicioDonantes:
    def __init__(self, repo: RepositorioDonantes, bus: BusEventos,
                 parametros: ParametrosElegibilidad | None = None) -> None:
        self.repo = repo
        self.bus = bus
        self.parametros = parametros or ParametrosElegibilidad()

    def registrar(self, donante: Donante) -> Donante:
        if not donante.consentimiento_datos:
            raise ValueError("Se requiere autorizar el tratamiento de datos personales (Ley 1581 de 2012).")
        if self.repo.por_documento(donante.documento):
            raise DonanteDuplicadoError("Ya existe un donante con ese documento.")
        self.repo.guardar(donante)
        self.bus.publicar("DonanteRegistrado", donante_id=donante.id, tipo=donante.tipo.value)
        return donante

    def evaluar(self, donante: Donante, hoy: date | None = None) -> ResultadoElegibilidad:
        hoy = hoy or date.today()
        p = self.parametros
        motivos: list[str] = []
        edad = donante.edad(hoy)
        if not p.edad_minima <= edad <= p.edad_maxima:
            motivos.append(f"Edad fuera del rango permitido ({p.edad_minima} a {p.edad_maxima} años).")
        if donante.peso_kg < p.peso_minimo_kg:
            motivos.append(f"Peso inferior a {p.peso_minimo_kg:.0f} kg.")
        if donante.ultima_donacion:
            dias = (hoy - donante.ultima_donacion).days
            if dias < p.intervalo_minimo_dias:
                motivos.append(f"Faltan {p.intervalo_minimo_dias - dias} días para cumplir el intervalo entre donaciones.")
        return ResultadoElegibilidad(elegible=not motivos, motivos=motivos)

    def registrar_donacion(self, donante: Donante, fecha: date) -> None:
        donante.ultima_donacion = fecha
        self.repo.guardar(donante)
