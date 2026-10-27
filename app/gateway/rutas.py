"""API Gateway: punto único de entrada.

Valida el token y el rol, traduce las peticiones HTTP a llamadas a los
módulos y devuelve respuestas JSON. Los módulos nunca se exponen
directamente al cliente.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.dominio import (Canal, Componente, Donante, NivelUrgencia, SolicitudUrgente,
                              TipoSanguineo)
from app.gateway.seguridad import USUARIOS_DEMO, autenticar, requiere_rol, usuario_actual
from app.modulos.donantes import DonanteDuplicadoError
from app.modulos.inventario import DonanteNoElegibleError

router = APIRouter(prefix="/api")


def c(request: Request):
    return request.app.state.contenedor


# Esquemas de entrada
class Credenciales(BaseModel):
    usuario: str
    clave: str


class NuevoDonante(BaseModel):
    documento: str = Field(min_length=5, max_length=15)
    nombre: str = Field(min_length=3)
    tipo: TipoSanguineo
    fecha_nacimiento: date
    peso_kg: float = Field(gt=0, lt=300)
    telefono: str
    correo: str
    canal: Canal = Canal.SMS
    latitud: float = 4.65
    longitud: float = -74.08
    consentimiento_datos: bool
    ultima_donacion: date | None = None


class NuevaDonacion(BaseModel):
    documento: str
    componente: Componente = Componente.GLOBULOS_ROJOS


class NuevaSolicitud(BaseModel):
    tipo_receptor: TipoSanguineo
    componente: Componente = Componente.GLOBULOS_ROJOS
    unidades_requeridas: int = Field(ge=1, le=20)
    urgencia: NivelUrgencia = NivelUrgencia.ALTA


class RespuestaAlerta(BaseModel):
    acepta: bool


class ModoFalla(BaseModel):
    activa: bool


# Serializadores
def _donante(d: Donante, ctx) -> dict:
    ev = ctx.donantes.evaluar(d)
    return {"id": d.id, "documento": d.documento, "nombre": d.nombre, "tipo": d.tipo.value,
            "edad": d.edad(date.today()), "peso_kg": d.peso_kg, "canal": d.canal.value,
            "ultima_donacion": d.ultima_donacion, "elegible": ev.elegible, "motivos": ev.motivos}


def _solicitud(s: SolicitudUrgente, ctx) -> dict:
    h = ctx.hospitales.get(s.hospital_id)
    return {"id": s.id, "hospital": h.nombre if h else s.hospital_id, "tipo_receptor": s.tipo_receptor.value,
            "componente": s.componente.value, "unidades_requeridas": s.unidades_requeridas,
            "unidades_reservadas": s.unidades_reservadas, "pendientes": s.unidades_pendientes(),
            "donantes_comprometidos": s.donantes_comprometidos, "urgencia": s.urgencia.value,
            "estado": s.estado.value, "fecha": s.fecha_creacion.strftime("%Y-%m-%d %H:%M:%S")}


def _circuito(ctx) -> dict:
    cb = ctx.circuito
    return {"estado": cb.estado.value, "fallos_consecutivos": cb.fallos_consecutivos,
            "umbral": cb.umbral_fallos, "espera_segundos": cb.tiempo_espera,
            "segundos_para_reintento": round(cb.segundos_para_reintento(), 1),
            "llamadas_rechazadas": cb.llamadas_rechazadas,
            "falla_simulada": ctx.proveedor.falla_activa}


# Autenticación
@router.post("/auth/login", tags=["Autenticación"])
def login(cred: Credenciales):
    token = autenticar(cred.usuario, cred.clave)
    datos = USUARIOS_DEMO[cred.usuario]
    return {"token": token, "rol": datos["rol"], "nombre": datos["nombre"]}


# Donantes
@router.post("/donantes", status_code=201, tags=["Donantes"])
def registrar_donante(datos: NuevoDonante, ctx=Depends(c)):
    try:
        donante = ctx.donantes.registrar(Donante(**datos.model_dump()))
    except DonanteDuplicadoError as e:
        raise HTTPException(409, str(e)) from None
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return _donante(donante, ctx)


@router.get("/donantes", tags=["Donantes"])
def listar_donantes(ctx=Depends(c), _u=Depends(requiere_rol("banco", "admin"))):
    return [_donante(d, ctx) for d in ctx.donantes.repo.todos()]


@router.get("/donantes/{documento}/elegibilidad", tags=["Donantes"])
def elegibilidad(documento: str, ctx=Depends(c)):
    d = ctx.donantes.repo.por_documento(documento)
    if not d:
        raise HTTPException(404, "Donante no encontrado")
    return _donante(d, ctx)


# Inventario
@router.post("/donaciones", status_code=201, tags=["Inventario"])
def registrar_donacion(datos: NuevaDonacion, ctx=Depends(c), u=Depends(requiere_rol("banco"))):
    d = ctx.donantes.repo.por_documento(datos.documento)
    if not d:
        raise HTTPException(404, "Donante no encontrado")
    try:
        unidad = ctx.inventario.registrar_donacion(d, u.get("sede_id", "SED1"), datos.componente)
    except DonanteNoElegibleError as e:
        raise HTTPException(422, f"Donante no elegible: {e}") from None
    return {"codigo": unidad.codigo, "tipo": unidad.tipo.value, "componente": unidad.componente.value,
            "vence": unidad.fecha_vencimiento, "estado": unidad.estado.value,
            "solicitud_id": unidad.solicitud_id}


@router.get("/inventario", tags=["Inventario"])
def inventario(ctx=Depends(c), _u=Depends(usuario_actual)):
    ctx.inventario.marcar_vencidas()
    return [{"codigo": x.codigo, "tipo": x.tipo.value, "componente": x.componente.value,
             "sede": ctx.sedes[x.sede_id].nombre, "vence": x.fecha_vencimiento, "estado": x.estado.value,
             "solicitud_id": x.solicitud_id}
            for x in sorted(ctx.inventario.repo.todas(), key=lambda x: x.fecha_vencimiento)]


# Solicitudes
@router.post("/solicitudes", status_code=201, tags=["Solicitudes"])
def publicar_solicitud(datos: NuevaSolicitud, ctx=Depends(c), u=Depends(requiere_rol("hospital"))):
    s = ctx.solicitudes.crear(SolicitudUrgente(hospital_id=u["hospital_id"], **datos.model_dump()))
    return _solicitud(s, ctx)


@router.get("/solicitudes", tags=["Solicitudes"])
def listar_solicitudes(ctx=Depends(c), _u=Depends(usuario_actual)):
    return [_solicitud(s, ctx) for s in ctx.solicitudes.repo.todas()]


# Alertas y notificaciones
@router.get("/alertas", tags=["Notificaciones"])
def listar_alertas(ctx=Depends(c), _u=Depends(usuario_actual)):
    salida = []
    for a in sorted(ctx.notificaciones.alertas.values(), key=lambda a: a.fecha, reverse=True):
        d = ctx.donantes.repo.por_id(a.donante_id)
        salida.append({"id": a.id, "solicitud_id": a.solicitud_id, "donante": d.nombre if d else a.donante_id,
                       "tipo": d.tipo.value if d else "", "canal": a.canal.value, "estado": a.estado.value,
                       "detalle": a.detalle, "fecha": a.fecha.strftime("%H:%M:%S")})
    return salida


@router.post("/alertas/{alerta_id}/respuesta", tags=["Notificaciones"])
def responder_alerta(alerta_id: str, datos: RespuestaAlerta, ctx=Depends(c)):
    """Simula el enlace que recibe el donante en el SMS o correo."""
    try:
        a = ctx.notificaciones.responder(alerta_id, datos.acepta)
    except KeyError as e:
        raise HTTPException(404, str(e)) from None
    except ValueError as e:
        raise HTTPException(409, str(e)) from None
    return {"id": a.id, "estado": a.estado.value, "detalle": a.detalle}


@router.get("/notificaciones/estado", tags=["Notificaciones"])
def estado_circuito(ctx=Depends(c), _u=Depends(usuario_actual)):
    return _circuito(ctx)


@router.post("/notificaciones/simular-falla", tags=["Notificaciones"])
def simular_falla(datos: ModoFalla, ctx=Depends(c), _u=Depends(requiere_rol("admin"))):
    ctx.proveedor.falla_activa = datos.activa
    return _circuito(ctx)


@router.post("/notificaciones/reintentar", tags=["Notificaciones"])
def reintentar(ctx=Depends(c), _u=Depends(requiere_rol("admin", "banco"))):
    enviadas = ctx.notificaciones.reintentar_pendientes()
    return {"reenviadas": enviadas, "circuito": _circuito(ctx)}


# Tablero
@router.get("/tablero", tags=["Tablero"])
def tablero(ctx=Depends(c), _u=Depends(usuario_actual)):
    ctx.inventario.marcar_vencidas()
    # Cache Aside: el tablero se consulta cada pocos segundos; el resumen se
    # recalcula solo cuando un evento de inventario invalida la caché.
    resumen = ctx.cache.obtener_o_cargar("inventario:resumen", ctx.inventario.resumen_disponible)
    return {
        "inventario": resumen,
        "criticos": [t for t, n in resumen.items() if n < 3],
        "solicitudes_activas": len(ctx.solicitudes.activas()),
        "donantes_registrados": len(ctx.donantes.repo.todos()),
        "donantes_elegibles": sum(ctx.donantes.evaluar(d).elegible for d in ctx.donantes.repo.todos()),
        "tasa_respuesta": ctx.notificaciones.tasa_respuesta(),
        "circuito": _circuito(ctx),
        "cache": ctx.cache.estadisticas(),
        "eventos": [{"tipo": e.tipo, "hora": e.fecha.strftime("%H:%M:%S"),
                     "datos": {k: v for k, v in e.datos.items() if k != "donantes"}
                     | ({"donantes": len(e.datos["donantes"])} if "donantes" in e.datos else {})}
                    for e in ctx.bus.ultimos(15)],
    }
