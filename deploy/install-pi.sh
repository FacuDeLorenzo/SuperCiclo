#!/usr/bin/env bash
# SuperCiclo — instalación en Raspberry Pi OS / Debian. Ver --help.
set -euo pipefail

# Repo por defecto para --quick (sobreescribible: SUPER_CICLO_REPO=https://…)
DEFAULT_GIT_REPO="${SUPER_CICLO_REPO:-https://github.com/hache-dev/SuperCiclo.git}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_REPO="$(cd "${SCRIPT_DIR}/.." && pwd)"

REPO_DIR="${REPO_DIR:-$DEFAULT_REPO}"
SERVICE_NAME="${SERVICE_NAME:-superciclo}"
PORT="${PORT:-8001}"
INSTALL_SYSTEMD=1
CLONE_URL=""
CLONE_DEST_GIVEN=0

die() {
  echo "Error: $*" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Falta el comando '$1'."
}

usage() {
  cat <<'EOF'
Uso: bash deploy/install-pi.sh [opciones]

  --quick             Igual que --clone con el repo por defecto (ver SUPER_CICLO_REPO en el script)
  --clone URL [DIR]   Clonar o actualizar (git pull) e instalar en DIR (default: ~/SuperCiclo)
  --port N            Puerto Flask (default: 8001 o variable PORT)
  --venv-only         Solo .venv + pip; no instala systemd
  --no-systemd        Igual que --venv-only
  -h, --help          Esta ayuda

Variables de entorno: REPO_DIR, SERVICE_NAME, PORT, SUPER_CICLO_REPO

Ejemplos:
  bash deploy/install-pi.sh --quick
  bash deploy/install-pi.sh
  bash deploy/install-pi.sh --clone https://github.com/hache-dev/SuperCiclo.git
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --quick)
      CLONE_URL="$DEFAULT_GIT_REPO"
      shift
      ;;
    --venv-only|--no-systemd)
      INSTALL_SYSTEMD=0
      shift
      ;;
    --port)
      [[ $# -ge 2 ]] || die "--port requiere un número"
      PORT="$2"
      shift 2
      ;;
    --clone)
      [[ $# -ge 2 ]] || die "--clone requiere la URL del repositorio"
      CLONE_URL="$2"
      shift 2
      if [[ $# -ge 1 && "$1" != --* ]]; then
        REPO_DIR="$1"
        CLONE_DEST_GIVEN=1
        shift
      fi
      ;;
    *)
      die "Opción desconocida: $1 (usá --help)"
      ;;
  esac
done

if [[ -n "$CLONE_URL" ]]; then
  if [[ "$CLONE_DEST_GIVEN" -eq 0 ]]; then
    REPO_DIR="${HOME}/SuperCiclo"
  fi
  if ! command -v git >/dev/null 2>&1; then
    need_cmd sudo
    echo "Instalando git ..."
    sudo apt-get update -qq
    sudo apt-get install -y git
  fi
  if [[ -d "$REPO_DIR/.git" ]]; then
    echo "Ya existe un repo en $REPO_DIR — actualizando con git pull."
    git -C "$REPO_DIR" pull --ff-only
  else
    [[ ! -e "$REPO_DIR" ]] || die "Ya existe $REPO_DIR y no es un clone; borralo o elegí otra ruta (--clone URL /ruta)."
    echo "Clonando en $REPO_DIR ..."
    git clone "$CLONE_URL" "$REPO_DIR"
  fi
fi

REPO_DIR="$(cd "$REPO_DIR" && pwd)"
echo "==> SuperCiclo en $REPO_DIR — venv, pip y servicio (si aplica)"
[[ -f "$REPO_DIR/app.py" ]] || die "No encuentro app.py en $REPO_DIR (¿repo correcto?)"
[[ -f "$REPO_DIR/requirements-pi.txt" ]] || die "No encuentro requirements-pi.txt en $REPO_DIR"

need_cmd python3
if ! python3 -c "import venv" 2>/dev/null; then
  need_cmd sudo
  echo "Instalando paquetes del sistema (python3-venv) ..."
  sudo apt-get update -qq
  sudo apt-get install -y python3-venv python3-full git
fi

VENV_PY="$REPO_DIR/.venv/bin/python"
VENV_PIP="$REPO_DIR/.venv/bin/pip"

if [[ ! -x "$VENV_PY" ]]; then
  echo "Creando entorno virtual en $REPO_DIR/.venv ..."
  python3 -m venv "$REPO_DIR/.venv"
fi

echo "Actualizando pip e instalando dependencias (requirements-pi.txt) ..."
"$VENV_PIP" install -q --upgrade pip
"$VENV_PIP" install -r "$REPO_DIR/requirements-pi.txt"

if [[ ! -f "$REPO_DIR/config.ini" ]]; then
  echo "Podés configurar el enchufe Tuya desde la web (${PORT:-8001}) → menú Dispositivo Tuya."
fi

if [[ "$INSTALL_SYSTEMD" -eq 0 ]]; then
  echo "Listo (solo venv). Para iniciar manualmente:"
  echo "  cd \"$REPO_DIR\" && . .venv/bin/activate && export FLASK_APP=app:app && flask run --host=0.0.0.0 --port $PORT"
  exit 0
fi

need_cmd sudo
RUN_USER="$(id -un)"
RUN_GROUP="$(id -gn)"

UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
TMP_UNIT="$(mktemp)"
trap 'rm -f "$TMP_UNIT"' EXIT

cat >"$TMP_UNIT" <<EOF
[Unit]
Description=SuperCiclo Flask backend
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${RUN_USER}
Group=${RUN_GROUP}
WorkingDirectory=${REPO_DIR}
Environment=FLASK_APP=app:app
Environment=PATH=${REPO_DIR}/.venv/bin
# Environment=SUPERCICLO_NO_AUTOSTART=1
ExecStart=${REPO_DIR}/.venv/bin/flask run --host=0.0.0.0 --port ${PORT}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

echo "Instalando unidad systemd en $UNIT_PATH (sudo) ..."
sudo cp "$TMP_UNIT" "$UNIT_PATH"
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"
sleep 1
sudo systemctl --no-pager status "$SERVICE_NAME" || true

IP_HINT="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo ""
echo "Deploy listo. Servicio: $SERVICE_NAME"
echo "  Estado:  sudo systemctl status $SERVICE_NAME"
echo "  Logs:    journalctl -u $SERVICE_NAME -f"
echo "  Web:     http://${IP_HINT:-IP-DE-LA-PI}:${PORT}/"
echo ""
