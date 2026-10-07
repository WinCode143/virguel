# Virguel — ERP operativo y tablero de control

Sistema centralizado para medir y proyectar la operación de calle: técnicos,
supervisores, incidentes, EPP, capacitación, flota, finanzas (egresos),
inventario y planificación de capacidad.

- **Gerencia / administración** → aplicación de escritorio (`/tablero/`) y carga de datos (`/admin/`).
- **Supervisores** → app móvil (`/app/`) + tableros de su equipo en la PC.
- **Técnicos** → app móvil (`/app/`), instalable en el celular.
- **Power BI** → vistas SQL en el esquema `powerbi` y CSV por web.

Documentación:
- [docs/REQUERIMIENTOS.md](docs/REQUERIMIENTOS.md) — qué pidió el cliente y cómo se resolvió cada punto.
- [docs/MANUAL.md](docs/MANUAL.md) — uso por rol.
- [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md) — estructura técnica, cálculos e instalación en servidor.
- [docs/BITACORA.md](docs/BITACORA.md) — registro de lo que se fue haciendo.
- [docs/TECNOLOGIAS.md](docs/TECNOLOGIAS.md) — tecnologías usadas.

## Puesta en marcha (desarrollo)

Requisitos: Python 3.12+, Docker, [uv](https://docs.astral.sh/uv/) (o pip).

```bash
cp .env.example .env              # completar claves
docker compose up -d              # PostgreSQL 16 en el puerto 5434
uv venv .venv && uv pip install -r requirements.txt --python .venv/bin/python
.venv/bin/python manage.py migrate
.venv/bin/python manage.py generar_demo --reset   # datos de prueba (opcional)
.venv/bin/python manage.py tareas_diarias         # encuestas + alertas
.venv/bin/python manage.py runserver
```

Abrir http://localhost:8000. Usuarios de demostración (contraseña `virguel2026`):

| Usuario | Rol |
|---|---|
| `gerencia` | Gerencia: todos los tableros |
| `admin` | Superusuario |
| `s001` … `s005` | Supervisores (`s004`: mal trato en encuestas; `s005`: casi no controla) |
| `t001` … `t036` | Técnicos |

## Comandos

| Comando | Qué hace |
|---|---|
| `manage.py tareas_diarias` | Genera encuestas del día, cierra objetivos vencidos y recalcula todas las alertas. Programarlo cada noche (ver ARQUITECTURA). |
| `manage.py generar_demo --reset` | **Borra** los datos operativos y genera 150 días de datos de prueba. |
| `manage.py crear_lector_powerbi --password …` | Usuario PostgreSQL de sólo lectura para Power BI. |
| `manage.py test tests` | Tests automáticos de las reglas de negocio. |
