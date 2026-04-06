#!/usr/bin/env bash
# Quick-start setup script for a Proxmox LXC (Debian/Ubuntu).
# Run as root once after cloning the repo.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_USER="opalx"

echo "==> Creating system user '$SERVICE_USER'..."
id "$SERVICE_USER" &>/dev/null || useradd -r -m -s /bin/bash "$SERVICE_USER"

echo "==> Creating /etc/opalx/secrets (edit to set OPALX_SECRET_KEY)..."
mkdir -p /etc/opalx
if [[ ! -f /etc/opalx/secrets ]]; then
    SECRET=$(python3 -c "import secrets; print('OPALX_SECRET_KEY=' + secrets.token_hex(32))")
    echo "$SECRET" > /etc/opalx/secrets
    chmod 600 /etc/opalx/secrets
    chown "$SERVICE_USER" /etc/opalx/secrets
    echo "    Generated secret key at /etc/opalx/secrets"
fi

echo "==> Installing Python venv and package..."
sudo -u "$SERVICE_USER" python3 -m venv "/home/$SERVICE_USER/.venv"
sudo -u "$SERVICE_USER" "/home/$SERVICE_USER/.venv/bin/pip" install -e "$REPO_DIR"

echo "==> Installing systemd service..."
cp "$REPO_DIR/deploy/opalx-regsuite.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable opalx-regsuite

echo ""
echo "Next steps:"
echo "  1. Edit /home/$SERVICE_USER/config.toml  (run: opalx-regsuite init)"
echo "  2. Add your first user: opalx-regsuite user-add --username admin"
echo "  3. Copy deploy/nginx.conf to /etc/nginx/sites-available/ and update the domain"
echo "  4. systemctl start opalx-regsuite"
echo "  5. systemctl status opalx-regsuite"
