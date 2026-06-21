#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# setup-pi.sh — one-shot Raspberry Pi setup for noise-catcher daemon
#
# Idempotent: safe to re-run. Installs system deps, clones/updates the repo,
# creates a venv, installs Python deps, and enables the systemd service.
# ---------------------------------------------------------------------------
set -euo pipefail

# --- Configuration ----------------------------------------------------------
REPO_URL="https://github.com/radiradichev/noise-catcher.git"
REPO_DIR="/home/pi/noise-catcher"
SERVICE_NAME="noise-catcher"
SERVICE_SRC="${REPO_DIR}/deploy/noise-catcher.service"
SERVICE_DST="/etc/systemd/system/${SERVICE_NAME}.service"
LOGROTATE_SRC="${REPO_DIR}/deploy/logrotate.conf"
LOGROTATE_DST="/etc/logrotate.d/${SERVICE_NAME}"

# --- System dependencies ----------------------------------------------------
echo ">>> Installing system dependencies..."
sudo apt update -qq
sudo apt install -y -qq \
    python3 \
    python3-venv \
    portaudio19-dev \
    git

# --- Clone or update repository --------------------------------------------
echo ">>> Setting up repository at ${REPO_DIR}..."
if [[ ! -d "${REPO_DIR}" ]]; then
    sudo -u pi git clone "${REPO_URL}" "${REPO_DIR}"
else
    sudo -u pi git -C "${REPO_DIR}" pull
fi

# --- Python virtual environment & dependencies ------------------------------
echo ">>> Creating Python virtual environment..."
sudo -u pi python3 -m venv "${REPO_DIR}/.venv"

echo ">>> Installing Python dependencies..."
# Use the venv's own pip to install uv, then uv for fast dependency resolution
"${REPO_DIR}/.venv/bin/pip" install --quiet uv
"${REPO_DIR}/.venv/bin/uv" pip install --quiet -e "${REPO_DIR}"

# Verify the CLI entry point exists
if [[ ! -x "${REPO_DIR}/.venv/bin/noise-catcher" ]]; then
    echo "ERROR: noise-catcher entry point not found after install" >&2
    exit 1
fi

# --- systemd service --------------------------------------------------------
echo ">>> Installing systemd service..."
if [[ -f "${SERVICE_SRC}" ]]; then
    sudo cp "${SERVICE_SRC}" "${SERVICE_DST}"
    sudo systemctl daemon-reload
    sudo systemctl enable "${SERVICE_NAME}"
    sudo systemctl restart "${SERVICE_NAME}"
    echo ">>> Service ${SERVICE_NAME} installed, enabled, and started."
else
    echo "WARNING: ${SERVICE_SRC} not found — skipping service installation"
fi

# --- Logrotate configuration ------------------------------------------------
echo ">>> Installing logrotate configuration..."
if [[ -f "${LOGROTATE_SRC}" ]]; then
    sudo cp "${LOGROTATE_SRC}" "${LOGROTATE_DST}"
else
    echo "WARNING: ${LOGROTATE_SRC} not found — skipping logrotate"
fi

# --- Status -----------------------------------------------------------------
echo ""
echo "=== Setup complete ==="
echo "Check status:  systemctl status ${SERVICE_NAME}"
echo "View logs:     journalctl -u ${SERVICE_NAME} -f"
echo "Database:      ${REPO_DIR}/noise_catcher.db"
echo "Rotated DBs:   ${REPO_DIR}/noise_catcher.YYYY-MM-DD.db"
