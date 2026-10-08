#!/usr/bin/env bash
# Levanta Virguel en esta PC y abre:
#   · el escritorio (gerencia) en Firefox
#   · la app del celular en una ventana con tamaño de teléfono (Chromium en modo app)
# Uso:  scripts/ver.sh            (todo)
#       scripts/ver.sh servidor   (sólo levantar, sin abrir ventanas)
set -e
cd "$(dirname "$0")/.."
PUERTO=8765
IP=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1)}')

echo "▶ Base de datos (PostgreSQL en Docker)…"
docker compose up -d db >/dev/null
until docker inspect -f '{{.State.Health.Status}}' virguel-postgres 2>/dev/null | grep -q healthy; do sleep 1; done

if ! curl -s -o /dev/null "http://127.0.0.1:$PUERTO/login/"; then
  echo "▶ Servidor web en el puerto $PUERTO…"
  # 0.0.0.0 = también accesible desde otros dispositivos de la red (celular en el mismo WiFi)
  DJANGO_ALLOWED_HOSTS="localhost,127.0.0.1,${IP}" nohup .venv/bin/python manage.py runserver "0.0.0.0:$PUERTO" \
    > /tmp/virguel-servidor.log 2>&1 &
  until curl -s -o /dev/null "http://127.0.0.1:$PUERTO/login/"; do sleep 1; done
fi

echo
echo "  Escritorio:        http://127.0.0.1:$PUERTO          (usuario: gerencia)"
echo "  App del celular:   http://127.0.0.1:$PUERTO/app/     (usuario: t014 o s002)"
[ -n "$IP" ] && echo "  Desde tu celular (mismo WiFi): http://$IP:$PUERTO"
echo "  Contraseña de todos los usuarios de prueba: virguel2026"
echo "  Registro del servidor: /tmp/virguel-servidor.log"
[ "$1" = "servidor" ] && exit 0

# Escritorio en Firefox
setsid nohup firefox --new-window "http://127.0.0.1:$PUERTO/" >/dev/null 2>&1 &

# App del celular: ventana angosta, perfil propio (sesión separada de la del escritorio)
CHROME=$(ls ~/.cache/ms-playwright/chromium-*/chrome-linux*/chrome 2>/dev/null | tail -1)
CHROME=${CHROME:-$(command -v chromium || command -v google-chrome || true)}
if [ -n "$CHROME" ]; then
  setsid nohup "$CHROME" --app="http://127.0.0.1:$PUERTO/app/" --window-size=412,880 \
    --user-data-dir="$HOME/.cache/virguel-celular" --no-first-run --no-default-browser-check \
    --user-agent="Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Mobile Safari/537.36" \
    >/dev/null 2>&1 &
else
  echo "  (No encontré Chromium: abrí http://127.0.0.1:$PUERTO/app/ en Firefox y apretá Ctrl+Shift+M para verla como celular)"
fi
