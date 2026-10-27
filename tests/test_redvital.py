"""Pruebas de las reglas de negocio, los patrones y el flujo completo."""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.contenedor import crear_contenedor
from app.core.cache import CacheTTL
from app.core.circuit_breaker import CircuitBreaker, CircuitoAbiertoError, EstadoCircuito
from app.core.dominio import Canal, Donante, TipoSanguineo as T
from app.main import app
from app.modulos.emparejamiento import ReglaGlobulosRojos, ReglaPlasma


# Strategy: reglas de compatibilidad
@pytest.mark.parametrize("receptor,esperado", [
    (T.O_NEG, {T.O_NEG}),
    (T.A_POS, {T.A_POS, T.A_NEG, T.O_POS, T.O_NEG}),
    (T.AB_POS, set(T)),
    (T.B_NEG, {T.B_NEG, T.O_NEG}),
])
def test_compatibilidad_globulos_rojos(receptor, esperado):
    assert set(ReglaGlobulosRojos().donantes_compatibles(receptor)) == esperado


def test_compatibilidad_plasma_es_inversa():
    assert set(ReglaPlasma().donantes_compatibles(T.AB_POS)) == {T.AB_POS, T.AB_NEG}
    assert T.O_NEG not in ReglaPlasma().donantes_compatibles(T.A_POS)


# Circuit Breaker
class Reloj:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_circuit_breaker_abre_y_se_recupera():
    reloj = Reloj()
    cb = CircuitBreaker(umbral_fallos=3, tiempo_espera=30, reloj=reloj)

    def falla():
        raise ConnectionError

    for _ in range(3):
        with pytest.raises(ConnectionError):
            cb.ejecutar(falla)
    assert cb.estado is EstadoCircuito.ABIERTO
    with pytest.raises(CircuitoAbiertoError):
        cb.ejecutar(lambda: "ok")
    reloj.t = 31
    assert cb.estado is EstadoCircuito.SEMIABIERTO
    assert cb.ejecutar(lambda: "ok") == "ok"
    assert cb.estado is EstadoCircuito.CERRADO


# Cache Aside
def test_cache_aside_lee_una_vez_hasta_invalidar():
    reloj, lecturas = Reloj(), []
    cache = CacheTTL(ttl_segundos=30, reloj=reloj)
    cargar = lambda: lecturas.append(1) or len(lecturas)
    assert cache.obtener_o_cargar("k", cargar) == 1
    assert cache.obtener_o_cargar("k", cargar) == 1
    cache.invalidar("k")
    assert cache.obtener_o_cargar("k", cargar) == 2


# Elegibilidad
def _donante(**cambios):
    datos = dict(documento="123456", nombre="Prueba", tipo=T.O_NEG, fecha_nacimiento=date(1995, 1, 1),
                 peso_kg=70, telefono="3000000000", correo="p@demo", latitud=4.6, longitud=-74.1,
                 canal=Canal.SMS)
    datos.update(cambios)
    return Donante(**datos)


def test_elegibilidad():
    c = crear_contenedor(sembrar=False)
    assert c.donantes.evaluar(_donante()).elegible
    assert not c.donantes.evaluar(_donante(peso_kg=45)).elegible
    reciente = _donante(ultima_donacion=date.today() - timedelta(days=10))
    resultado = c.donantes.evaluar(reciente)
    assert not resultado.elegible and "intervalo" in resultado.motivos[0]


# Flujo completo a través del API Gateway
def _token(cliente, usuario, clave):
    return {"Authorization": "Bearer " + cliente.post("/api/auth/login", json={"usuario": usuario, "clave": clave}).json()["token"]}


def test_flujo_solicitud_alertas_y_circuito():
    app.state.contenedor = crear_contenedor()
    cliente = TestClient(app)
    hosp = _token(cliente, "hospital", "hospital123")
    admin = _token(cliente, "admin", "admin123")

    # Sin token o con rol equivocado, el gateway rechaza
    assert cliente.post("/api/solicitudes", json={"tipo_receptor": "O-", "unidades_requeridas": 1}).status_code == 401
    assert cliente.post("/api/solicitudes", headers=admin, json={"tipo_receptor": "O-", "unidades_requeridas": 1}).status_code == 403

    # Solicitud de O- que supera el inventario: reserva lo disponible y alerta donantes
    r = cliente.post("/api/solicitudes", headers=hosp, json={"tipo_receptor": "O-", "unidades_requeridas": 3, "urgencia": "CRÍTICA"})
    assert r.status_code == 201
    s = r.json()
    assert s["unidades_reservadas"] == 1 and s["pendientes"] == 2
    alertas = cliente.get("/api/alertas", headers=admin).json()
    assert alertas and all(a["estado"] == "ENVIADA" for a in alertas)

    # El donante acepta
    r = cliente.post(f"/api/alertas/{alertas[0]['id']}/respuesta", json={"acepta": True})
    assert r.json()["estado"] == "ACEPTADA"

    # Cae el proveedor: tras 3 fallos el circuito se abre y las alertas quedan pendientes
    cliente.post("/api/notificaciones/simular-falla", headers=admin, json={"activa": True})
    cliente.post("/api/solicitudes", headers=hosp, json={"tipo_receptor": "O-", "unidades_requeridas": 2})
    estado = cliente.get("/api/notificaciones/estado", headers=admin).json()
    assert estado["estado"] == "ABIERTO" and estado["llamadas_rechazadas"] >= 1
    pendientes = [a for a in cliente.get("/api/alertas", headers=admin).json() if a["estado"] == "PENDIENTE REINTENTO"]
    assert pendientes

    # La publicación de solicitudes nunca se bloqueó (RNF08)
    assert len(cliente.get("/api/solicitudes", headers=hosp).json()) == 2


def test_donacion_se_asigna_a_solicitud_abierta():
    app.state.contenedor = crear_contenedor()
    cliente = TestClient(app)
    hosp = _token(cliente, "hospital", "hospital123")
    banco = _token(cliente, "banco", "banco123")
    s = cliente.post("/api/solicitudes", headers=hosp, json={"tipo_receptor": "O-", "unidades_requeridas": 5}).json()
    cliente.post("/api/donantes", json={
        "documento": "99887766", "nombre": "Nuevo Donante", "tipo": "O-", "fecha_nacimiento": "1990-03-03",
        "peso_kg": 72, "telefono": "3110000000", "correo": "n@demo", "consentimiento_datos": True})
    u = cliente.post("/api/donaciones", headers=banco, json={"documento": "99887766"}).json()
    assert u["solicitud_id"] == s["id"]
    # Donar de nuevo el mismo día no es posible
    assert cliente.post("/api/donaciones", headers=banco, json={"documento": "99887766"}).status_code == 422


def test_reiniciar_demo_solo_admin_y_restablece_datos():
    app.state.contenedor = crear_contenedor()
    cliente = TestClient(app)
    hosp = _token(cliente, "hospital", "hospital123")
    admin = _token(cliente, "admin", "admin123")
    cliente.post("/api/solicitudes", headers=hosp, json={"tipo_receptor": "O-", "unidades_requeridas": 1})
    assert cliente.post("/api/demo/reiniciar", headers=hosp).status_code == 403
    assert cliente.post("/api/demo/reiniciar", headers=admin).status_code == 200
    assert cliente.get("/api/solicitudes", headers=admin).json() == []
