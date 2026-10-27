"""Entidades y tipos compartidos del dominio RedVital."""
from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum


class TipoSanguineo(str, Enum):
    O_NEG = "O-"
    O_POS = "O+"
    A_NEG = "A-"
    A_POS = "A+"
    B_NEG = "B-"
    B_POS = "B+"
    AB_NEG = "AB-"
    AB_POS = "AB+"


class Componente(str, Enum):
    GLOBULOS_ROJOS = "Glóbulos rojos"
    PLAQUETAS = "Plaquetas"
    PLASMA = "Plasma"


class EstadoUnidad(str, Enum):
    DISPONIBLE = "DISPONIBLE"
    RESERVADA = "RESERVADA"
    DESPACHADA = "DESPACHADA"
    VENCIDA = "VENCIDA"


class NivelUrgencia(str, Enum):
    CRITICA = "CRÍTICA"
    ALTA = "ALTA"
    MEDIA = "MEDIA"


class EstadoSolicitud(str, Enum):
    ABIERTA = "ABIERTA"
    EN_ATENCION = "EN ATENCIÓN"
    CUBIERTA = "CUBIERTA"


class Canal(str, Enum):
    SMS = "SMS"
    CORREO = "Correo"


class EstadoAlerta(str, Enum):
    ENVIADA = "ENVIADA"
    PENDIENTE_REINTENTO = "PENDIENTE REINTENTO"
    ACEPTADA = "ACEPTADA"
    RECHAZADA = "RECHAZADA"


def nuevo_id() -> str:
    return uuid.uuid4().hex[:8].upper()


@dataclass
class Sede:
    id: str
    nombre: str
    municipio: str
    latitud: float
    longitud: float


@dataclass
class Hospital:
    id: str
    nombre: str
    municipio: str
    latitud: float
    longitud: float


@dataclass
class Donante:
    documento: str
    nombre: str
    tipo: TipoSanguineo
    fecha_nacimiento: date
    peso_kg: float
    telefono: str
    correo: str
    latitud: float
    longitud: float
    canal: Canal = Canal.SMS
    consentimiento_datos: bool = True
    ultima_donacion: date | None = None
    id: str = field(default_factory=nuevo_id)

    def edad(self, hoy: date) -> int:
        cumplio = (hoy.month, hoy.day) >= (self.fecha_nacimiento.month, self.fecha_nacimiento.day)
        return hoy.year - self.fecha_nacimiento.year - (0 if cumplio else 1)


@dataclass
class UnidadSangre:
    tipo: TipoSanguineo
    componente: Componente
    sede_id: str
    fecha_extraccion: date
    fecha_vencimiento: date
    estado: EstadoUnidad = EstadoUnidad.DISPONIBLE
    solicitud_id: str | None = None
    codigo: str = field(default_factory=lambda: "U" + nuevo_id())

    def esta_vencida(self, hoy: date) -> bool:
        return hoy > self.fecha_vencimiento


@dataclass
class SolicitudUrgente:
    hospital_id: str
    tipo_receptor: TipoSanguineo
    componente: Componente
    unidades_requeridas: int
    urgencia: NivelUrgencia
    estado: EstadoSolicitud = EstadoSolicitud.ABIERTA
    unidades_reservadas: int = 0
    donantes_comprometidos: int = 0
    fecha_creacion: datetime = field(default_factory=datetime.now)
    id: str = field(default_factory=lambda: "S" + nuevo_id())

    def unidades_pendientes(self) -> int:
        return max(0, self.unidades_requeridas - self.unidades_reservadas)


@dataclass
class Alerta:
    solicitud_id: str
    donante_id: str
    canal: Canal
    estado: EstadoAlerta
    detalle: str = ""
    fecha: datetime = field(default_factory=datetime.now)
    id: str = field(default_factory=lambda: "A" + nuevo_id())


def distancia_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia aproximada entre dos coordenadas (fórmula del haversine)."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
