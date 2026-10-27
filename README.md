# RedVital

Prototipo académico de una plataforma que conecta bancos de sangre, hospitales y donantes. Cuando un hospital publica una solicitud urgente, el sistema reserva unidades compatibles del inventario y, si no alcanzan, alerta a los donantes compatibles, elegibles y más cercanos.

Curso: Arquitectura de Software. Ingeniería de Software, Tecnológica del Oriente, 2026.

[![Pruebas](https://github.com/Bait07/redvital-prototipo/actions/workflows/pruebas.yml/badge.svg)](https://github.com/Bait07/redvital-prototipo/actions/workflows/pruebas.yml)

* Prototipo desplegado: https://redvital-w17f.onrender.com
* Documentación de la API: https://redvital-w17f.onrender.com/docs
* Diagramas UML (PlantUML): [docs/diagramas](docs/diagramas)

## Arquitectura

El prototipo se ejecuta como un único servicio web (para caber en el plan gratuito de Render), pero está organizado en módulos independientes con los mismos límites que tendrían los microservicios de la arquitectura objetivo:

```
app/
├── gateway/          API Gateway: autenticación JWT, roles, límite de tasa, enrutamiento
├── modulos/
│   ├── donantes.py       registro y elegibilidad (Repository)
│   ├── solicitudes.py    solicitudes urgentes (publica SolicitudCreada)
│   ├── inventario.py     unidades, vencimientos y reservas
│   ├── emparejamiento.py compatibilidad ABO/Rh (Strategy) y Cache Aside
│   └── notificaciones.py alertas protegidas con Circuit Breaker
├── core/
│   ├── eventos.py        bus Publicador/Suscriptor
│   ├── circuit_breaker.py
│   ├── cache.py          caché con tiempo de vida (Cache Aside)
│   └── dominio.py        entidades
├── contenedor.py     raíz de composición y datos de demostración
└── static/index.html panel web
```

Los módulos no acceden a los datos internos de otros: se comunican por eventos o por interfaces públicas. Para pasar a la arquitectura objetivo basta con reemplazar en `contenedor.py` los repositorios en memoria por PostgreSQL, el bus por un broker gestionado y la caché por Redis.

| Patrón | Dónde se ve |
|---|---|
| API Gateway | `app/gateway/` y middleware en `app/main.py` |
| Publicador/Suscriptor | `app/core/eventos.py`; panel "Bus de eventos" del tablero |
| Circuit Breaker | `app/core/circuit_breaker.py`; pestaña "Alertas y resiliencia" |
| Cache Aside | `app/core/cache.py`; indicador "Aciertos de caché" |
| Repository | interfaces `Repositorio*` en cada módulo |
| Strategy | `ReglaGlobulosRojos` y `ReglaPlasma` en `emparejamiento.py` |

## Ejecutar en local

```bash
python -m venv .venv
source .venv/bin/activate        # en Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

Abrir http://localhost:8000 (panel) y http://localhost:8000/docs (documentación de la API).

Pruebas: `pytest` (también se ejecutan en GitHub Actions en cada push).

Con Docker:

```bash
docker build -t redvital .
docker run -p 8000:8000 redvital
```

## Usuarios de demostración

| Rol | Usuario | Clave |
|---|---|---|
| Hospital | hospital | hospital123 |
| Banco de sangre | banco | banco123 |
| Administrador | admin | admin123 |

En el panel basta con pulsar el botón del rol. El registro de donantes y la respuesta a alertas son públicos, como lo serían en el enlace que recibe el donante.

## Despliegue en Render

1. Subir este repositorio a GitHub.
2. En https://render.com iniciar sesión con GitHub.
3. New, Blueprint, elegir el repositorio. Render lee `render.yaml` y crea el servicio `redvital` en el plan gratuito.
4. Esperar a que el estado sea "Live" y abrir la URL `https://redvital-xxxx.onrender.com`.

Alternativa manual: New, Web Service, elegir el repositorio y configurar:

* Build command: `pip install -r requirements.txt`
* Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
* Instance type: Free

Nota: el plan gratuito apaga el servicio tras 15 minutos sin uso y tarda cerca de un minuto en reactivarse. Abrir la URL un par de minutos antes de la demostración. Los datos están en memoria y se restablecen en cada reinicio.

## Guion corto de demostración

1. Tablero (rol Hospital): inventario por tipo con O- en nivel crítico.
2. Solicitudes: publicar 3 unidades O-, urgencia CRÍTICA. Se reserva la única unidad disponible y se alerta a donantes por las 2 faltantes.
3. Tablero: ver en el bus los eventos SolicitudCreada, InventarioActualizado y DonantesSeleccionados.
4. Alertas (rol Administrador): un donante acepta la alerta.
5. Simular caída del proveedor y publicar otra solicitud: tras 3 fallos el circuito pasa a ABIERTO y las alertas quedan en cola de reintento sin bloquear la publicación.
6. Restablecer el proveedor, esperar 30 s y pulsar "Reintentar pendientes": el circuito vuelve a CERRADO y se envían las alertas.
7. Inventario (rol Banco): registrar la donación de un donante elegible; la unidad se asigna sola a la solicitud abierta.

Para volver a los datos iniciales: rol Administrador, pestaña "Alertas y resiliencia", botón "Reiniciar datos de demo" (o `POST /api/demo/reiniciar` desde /docs).
