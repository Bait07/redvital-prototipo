"""Autenticación con JWT y autorización por rol (API Gateway)."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

CLAVE_SECRETA = os.getenv("JWT_SECRET", "clave-solo-para-desarrollo-cambiar-en-render")
ALGORITMO = "HS256"

# Usuarios de demostración. En la arquitectura objetivo vienen de un
# proveedor de identidad y las claves se guardan con hash.
USUARIOS_DEMO = {
    "hospital": {"clave": "hospital123", "rol": "hospital", "nombre": "Clínica Santa Lucía", "hospital_id": "HOS1"},
    "banco": {"clave": "banco123", "rol": "banco", "nombre": "Bacterióloga Sede Centro", "sede_id": "SED1"},
    "admin": {"clave": "admin123", "rol": "admin", "nombre": "Administrador RedVital"},
}

_esquema = HTTPBearer(auto_error=False)


def emitir_token(usuario: str) -> str:
    datos = USUARIOS_DEMO[usuario]
    carga = {"sub": usuario, "rol": datos["rol"],
             "exp": datetime.now(timezone.utc) + timedelta(hours=8)}
    return jwt.encode(carga, CLAVE_SECRETA, algorithm=ALGORITMO)


def autenticar(usuario: str, clave: str) -> str:
    datos = USUARIOS_DEMO.get(usuario)
    if not datos or datos["clave"] != clave:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Usuario o clave incorrectos")
    return emitir_token(usuario)


def usuario_actual(cred: HTTPAuthorizationCredentials | None = Depends(_esquema)) -> dict:
    if cred is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Falta el token de acceso")
    try:
        carga = jwt.decode(cred.credentials, CLAVE_SECRETA, algorithms=[ALGORITMO])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido o vencido") from None
    return {**USUARIOS_DEMO[carga["sub"]], "usuario": carga["sub"]}


def requiere_rol(*roles: str):
    def verificar(usuario: dict = Depends(usuario_actual)) -> dict:
        if usuario["rol"] not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Su rol no tiene permiso para esta operación")
        return usuario
    return verificar
