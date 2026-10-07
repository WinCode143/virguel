# Documentación del proyecto Virguel

| Documento | Para quién | Qué contiene |
|---|---|---|
| [REQUERIMIENTOS.md](REQUERIMIENTOS.md) | Todos | Qué pidió el cliente, cómo se resolvió cada punto y qué falta confirmar. **Empezar por acá.** |
| [MANUAL.md](MANUAL.md) | Usuarios | Cómo se usa el sistema según el rol (técnico, supervisor, gerencia). |
| [METRICAS.md](METRICAS.md) | Gerencia | Indicadores de productividad (IPT técnicos, IGS supervisores): fórmulas, metas y por qué. |
| [ARQUITECTURA.md](ARQUITECTURA.md) | Técnicos de sistemas | Estructura, cálculos, seguridad e instalación en servidor. |
| [TECNOLOGIAS.md](TECNOLOGIAS.md) | Técnicos de sistemas | Tecnologías usadas y para qué. |
| [BITACORA.md](BITACORA.md) | Todos | Registro cronológico de lo que se hizo, decisiones y problemas corregidos. |

## Mapa del sistema

| Parte | Dirección | Quién la usa |
|---|---|---|
| Escritorio (tableros) | `/tablero/`, `/personal/` | Gerencia, administración, supervisores (sólo su equipo) |
| App de campo (celular) | `/app/` | Técnicos y supervisores |
| Carga de datos | `/admin/` | Gerencia y administración |
| Encuesta por link | `/encuesta/<código>/` | Técnicos (sin iniciar sesión) |
| Power BI / CSV | esquema `powerbi` en PostgreSQL, `/api/powerbi/` | Gerencia |
