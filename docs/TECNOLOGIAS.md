# Tecnologías utilizadas

| Tecnología | Versión | Para qué se usa |
|---|---|---|
| Python | 3.13 | Lenguaje del backend. |
| Django | 5.2 LTS | Framework web: modelos/ORM, migraciones, admin, autenticación, vistas y plantillas. |
| PostgreSQL | 16 (imagen `postgres:16-alpine`) | Base de datos principal. |
| psycopg | 3.x (binary) | Driver de PostgreSQL para Python. |
| Docker / Docker Compose | — | Levantar PostgreSQL aislado (`docker compose up -d`). |
| uv | — | Crear el entorno virtual e instalar dependencias rápido. |
| git | — | Control de versiones. |
| gunicorn | 23 | Servidor de aplicación Python en producción. |
| Caddy | 2 | Proxy web en producción con certificado HTTPS automático (Let's Encrypt). |
| pywebpush | 2.x | Enviar notificaciones push (Web Push / VAPID) al celular de técnicos y supervisores. |
| Web Push API + Canvas | estándar web | Notificaciones en el celular y firma del cliente con el dedo al cerrar una orden. |
| openpyxl | 3.1 | Leer archivos Excel (.xlsx) en la importación masiva. |
| Inter (Google Fonts) | — | Tipografía de la interfaz (si no carga, se usa la del sistema). |
| Íconos SVG propios | — | Sprite `static/img/iconos.svg` (49 íconos de línea); reemplaza emojis que se ven distinto en cada celular. |
| Chart.js | 4.4.7 (servido localmente en `static/vendor/`) | Gráficos de los tableros. |
| PWA (Web App Manifest + Service Worker) | estándar web | App de campo instalable en el celular sin pasar por tiendas de apps. |
| Geolocation API / captura de cámara (HTML) | estándar web | Ubicación y foto en los informes de control del supervisor. |
| Power BI | — | Herramienta de análisis del cliente; se conecta a las vistas `powerbi.*` o a los CSV. |
| Playwright + Chromium headless | 1.55 (sólo en desarrollo) | Capturas de pantalla para revisión visual. No forma parte del sistema. |
| ruff | — (sólo en desarrollo) | Linter de Python. |

## Decisiones de no-uso
- **Sin framework de frontend (React/Vue)**: plantillas de Django + CSS propio. Menos
  piezas que mantener; la interactividad necesaria es poca.
- **Sin app nativa (Android/iOS)**: una PWA cubre lo necesario (instalable, cámara, GPS)
  y se actualiza sola al publicar cambios.
- **Sin Oracle**: pedido explícito del cliente.
- **Sin dependencias extra para leer `.env`**: un lector de 10 líneas en `config/settings.py`.
