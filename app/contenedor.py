"""Raíz de composición: crea y conecta los módulos.

Es el único lugar que conoce las implementaciones concretas (repositorios
en memoria, proveedor simulado). Para pasar a la arquitectura objetivo
basta con cambiar aquí las implementaciones.
"""
from __future__ import annotations

import os
import random
from dataclasses import dataclass
from datetime import date, timedelta

from app.core.cache import CacheTTL
from app.core.circuit_breaker import CircuitBreaker
from app.core.dominio import (Canal, Componente, Donante, EstadoUnidad, Hospital, Sede,
                              TipoSanguineo, UnidadSangre)
from app.core.eventos import BusEventos
from app.modulos.donantes import RepositorioDonantesMemoria, ServicioDonantes
from app.modulos.emparejamiento import ServicioEmparejamiento
from app.modulos.inventario import RepositorioInventarioMemoria, ServicioInventario, VIDA_UTIL_DIAS
from app.modulos.notificaciones import ProveedorSimulado, ServicioNotificaciones
from app.modulos.solicitudes import RepositorioSolicitudesMemoria, ServicioSolicitudes


@dataclass
class Contenedor:
    bus: BusEventos
    cache: CacheTTL
    circuito: CircuitBreaker
    proveedor: ProveedorSimulado
    sedes: dict[str, Sede]
    hospitales: dict[str, Hospital]
    donantes: ServicioDonantes
    inventario: ServicioInventario
    solicitudes: ServicioSolicitudes
    emparejamiento: ServicioEmparejamiento
    notificaciones: ServicioNotificaciones


def crear_contenedor(sembrar: bool = True) -> Contenedor:
    bus = BusEventos()
    cache = CacheTTL(ttl_segundos=float(os.getenv("CACHE_TTL", "30")))
    circuito = CircuitBreaker(umbral_fallos=int(os.getenv("CB_UMBRAL", "3")),
                              tiempo_espera=float(os.getenv("CB_ESPERA", "30")))
    proveedor = ProveedorSimulado()

    sedes = {s.id: s for s in [
        Sede("SED1", "Banco de Sangre Sede Centro", "Bogotá", 4.6097, -74.0817),
        Sede("SED2", "Banco de Sangre Sede Norte", "Bogotá", 4.7110, -74.0300),
    ]}
    hospitales = {h.id: h for h in [
        Hospital("HOS1", "Clínica Santa Lucía (ficticia)", "Bogotá", 4.6486, -74.0628),
        Hospital("HOS2", "Hospital Regional El Prado (ficticio)", "Soacha", 4.5794, -74.2168),
    ]}

    repo_donantes = RepositorioDonantesMemoria()
    donantes = ServicioDonantes(repo_donantes, bus)
    inventario = ServicioInventario(RepositorioInventarioMemoria(), donantes, bus)
    solicitudes = ServicioSolicitudes(RepositorioSolicitudesMemoria(), bus)
    emparejamiento = ServicioEmparejamiento(bus, cache, solicitudes, inventario, donantes,
                                            repo_donantes, hospitales)
    notificaciones = ServicioNotificaciones(bus, proveedor, circuito, repo_donantes, solicitudes)

    c = Contenedor(bus, cache, circuito, proveedor, sedes, hospitales, donantes, inventario,
                   solicitudes, emparejamiento, notificaciones)
    if sembrar:
        sembrar_datos(c)
    return c


NOMBRES = ["Laura Gómez", "Andrés Rojas", "Camila Torres", "Julián Pérez", "Valentina Díaz",
           "Santiago Castro", "Daniela Ruiz", "Felipe Moreno", "Mariana López", "Sebastián Vargas",
           "Natalia Herrera", "Mateo Jiménez", "Isabella Ramírez", "Nicolás Suárez", "Sara Medina",
           "Tomás Ortiz", "Paula Cárdenas", "David Ríos", "Juliana Mejía", "Alejandro Silva",
           "Carolina Peña", "Esteban Guerrero", "Manuela Acosta", "Miguel Restrepo", "Luisa Molina",
           "Cristian Parra", "Gabriela Rincón", "Samuel Duarte", "Ana María León", "Jorge Salazar"]
# Distribución aproximada de tipos sanguíneos para la simulación.
PESOS_TIPOS = {"O+": 55, "A+": 24, "B+": 8, "O-": 5, "AB+": 3, "A-": 3, "B-": 1, "AB-": 1}


def sembrar_datos(c: Contenedor) -> None:
    rnd = random.Random(2026)
    hoy = date.today()
    tipos = list(PESOS_TIPOS)
    for i, nombre in enumerate(NOMBRES):
        tipo = TipoSanguineo(rnd.choices(tipos, weights=list(PESOS_TIPOS.values()))[0])
        if i < 4:
            tipo = TipoSanguineo.O_NEG  # garantiza donantes O negativo para la demo
        ultima = hoy - timedelta(days=rnd.choice([30, 60, 120, 200, 400])) if rnd.random() < 0.7 else None
        donante = Donante(
            documento=str(1000000000 + i * 7919), nombre=nombre, tipo=tipo,
            fecha_nacimiento=date(hoy.year - rnd.randint(19, 58), rnd.randint(1, 12), rnd.randint(1, 28)),
            peso_kg=round(rnd.uniform(52, 95), 1), telefono=f"3{rnd.randint(100000000, 209999999)}",
            correo=f"donante{i + 1}@correo.demo", latitud=4.60 + rnd.uniform(-0.08, 0.12),
            longitud=-74.08 + rnd.uniform(-0.08, 0.06),
            canal=Canal.SMS if i % 3 else Canal.CORREO, ultima_donacion=ultima)
        c.donantes.repo.guardar(donante)

    existencias = {"O+": 9, "A+": 6, "B+": 3, "AB+": 2, "O-": 1, "A-": 2, "B-": 1, "AB-": 0}
    for tipo, cantidad in existencias.items():
        for _ in range(cantidad):
            dias = rnd.randint(1, 30)
            c.inventario.repo.guardar(UnidadSangre(
                tipo=TipoSanguineo(tipo), componente=Componente.GLOBULOS_ROJOS,
                sede_id=rnd.choice(list(c.sedes)), fecha_extraccion=hoy - timedelta(days=dias),
                fecha_vencimiento=hoy - timedelta(days=dias) + timedelta(days=VIDA_UTIL_DIAS[Componente.GLOBULOS_ROJOS]),
                estado=EstadoUnidad.DISPONIBLE))
    for tipo in ["O+", "A+", "AB+"]:
        c.inventario.repo.guardar(UnidadSangre(
            tipo=TipoSanguineo(tipo), componente=Componente.PLASMA, sede_id="SED1",
            fecha_extraccion=hoy - timedelta(days=20), fecha_vencimiento=hoy + timedelta(days=345)))
