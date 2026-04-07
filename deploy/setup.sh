#!/usr/bin/env bash
# setup.sh — Full first-time setup for the OPALX Regression Suite on a Proxmox LXC
# (Debian/Ubuntu). Run as root once after cloning this repo.
#
# What this script does:
#   1.  Creates the 'opalx' system user.
#   2.  Clones OPALX and regression-tests-x into /home/opalx/.
#   3.  Prompts for the test-data directory (data_root).
#   4.  Installs the Python package into a venv.
#   5.  Writes /home/opalx/config.toml and /etc/opalx/secrets.
#   6.  Installs and enables the systemd service.
#   7.  Prompts to create the first admin user.
#
# Usage:
#   sudo bash deploy/setup.sh
set -euo pipefail

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
info()    { echo -e "\e[1;34m==>\e[0m $*"; }
success() { echo -e "\e[1;32m  ✓\e[0m $*"; }
warn()    { echo -e "\e[1;33m  !\e[0m $*"; }
die()     { echo -e "\e[1;31m[FATAL]\e[0m $*" >&2; exit 1; }

require_root() {
    [[ $EUID -eq 0 ]] || die "This script must be run as root (try: sudo bash $0)."
}

require_cmd() {
    command -v "$1" &>/dev/null || die "Required command '$1' not found. Install it and re-run."
}

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_USER="opalx"
HOME_DIR="/home/$SERVICE_USER"
VENV="$HOME_DIR/.venv"
CONFIG_PATH="$HOME_DIR/config.toml"
SECRETS_PATH="/etc/opalx/secrets"

OPALX_REPO_URL="https://github.com/OPALX-project/OPALX.git"
REGTESTS_REPO_URL="https://github.com/OPALX-project/regression-tests-x.git"

OPALX_CLONE_DIR="$HOME_DIR/OPALX"
REGTESTS_CLONE_DIR="$HOME_DIR/regression-tests-x"
BUILDS_DIR="$HOME_DIR/builds"

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
require_root
require_cmd python3
require_cmd git

# ---------------------------------------------------------------------------
# Step 1 — System user
# ---------------------------------------------------------------------------
info "Creating system user '$SERVICE_USER'..."
if id "$SERVICE_USER" &>/dev/null; then
    warn "User '$SERVICE_USER' already exists — skipping creation."
else
    useradd -r -m -s /bin/bash "$SERVICE_USER"
    success "User '$SERVICE_USER' created."
fi

# ---------------------------------------------------------------------------
# Step 2 — Clone OPALX
# ---------------------------------------------------------------------------
info "Cloning OPALX from $OPALX_REPO_URL..."
if [[ -d "$OPALX_CLONE_DIR/.git" ]]; then
    warn "OPALX already cloned at $OPALX_CLONE_DIR — pulling latest."
    sudo -u "$SERVICE_USER" git -C "$OPALX_CLONE_DIR" pull --ff-only
else
    sudo -u "$SERVICE_USER" git clone --depth=1 "$OPALX_REPO_URL" "$OPALX_CLONE_DIR"
    success "OPALX cloned to $OPALX_CLONE_DIR"
fi

# ---------------------------------------------------------------------------
# Step 3 — Clone regression-tests-x
# ---------------------------------------------------------------------------
info "Cloning regression-tests-x from $REGTESTS_REPO_URL..."
if [[ -d "$REGTESTS_CLONE_DIR/.git" ]]; then
    warn "regression-tests-x already cloned at $REGTESTS_CLONE_DIR — pulling latest."
    sudo -u "$SERVICE_USER" git -C "$REGTESTS_CLONE_DIR" pull --ff-only
else
    sudo -u "$SERVICE_USER" git clone --depth=1 "$REGTESTS_REPO_URL" "$REGTESTS_CLONE_DIR"
    success "regression-tests-x cloned to $REGTESTS_CLONE_DIR"
fi

# ---------------------------------------------------------------------------
# Step 4 — Prompt for test-data directory (data_root)
# ---------------------------------------------------------------------------
echo ""
echo "  The test-data directory (data_root) stores all regression run results,"
echo "  indexes, and logs. It can live anywhere on this machine."
echo "  Examples:"
echo "    /srv/opalx/test-data      (dedicated storage mount)"
echo "    $HOME_DIR/test-data       (inside the opalx home dir)"
echo ""

if [[ -n "${OPALX_DATA_ROOT:-}" ]]; then
    DATA_ROOT="$OPALX_DATA_ROOT"
    info "Using data_root from environment: $DATA_ROOT"
else
    read -rp "  Enter path for test-data (data_root) [default: $HOME_DIR/test-data]: " DATA_ROOT_INPUT
    DATA_ROOT="${DATA_ROOT_INPUT:-$HOME_DIR/test-data}"
fi

# Expand ~ if the user typed it
DATA_ROOT="${DATA_ROOT/#\~/$HOME}"

info "Creating data_root at $DATA_ROOT..."
mkdir -p "$DATA_ROOT"
chown -R "$SERVICE_USER:$SERVICE_USER" "$DATA_ROOT"
success "data_root ready: $DATA_ROOT"

# Also create the builds directory
mkdir -p "$BUILDS_DIR"
chown "$SERVICE_USER:$SERVICE_USER" "$BUILDS_DIR"

# ---------------------------------------------------------------------------
# Step 5 — Secret key and SSH key directory
# ---------------------------------------------------------------------------
info "Setting up /etc/opalx/secrets..."
mkdir -p /etc/opalx

# SSH keys are kept outside data_root so they are never co-located with
# test-data that may be archived or shared as a data repository.
SSH_KEYS_DIR="/etc/opalx/ssh-keys"
if [[ ! -d "$SSH_KEYS_DIR" ]]; then
    mkdir -p "$SSH_KEYS_DIR"
    chmod 700 "$SSH_KEYS_DIR"
    chown "$SERVICE_USER" "$SSH_KEYS_DIR"
    success "Created SSH keys directory at $SSH_KEYS_DIR"
else
    warn "SSH keys directory already exists at $SSH_KEYS_DIR — skipping."
fi
if [[ ! -f "$SECRETS_PATH" ]]; then
    SECRET=$(python3 -c "import secrets; print('OPALX_SECRET_KEY=' + secrets.token_hex(32))")
    echo "$SECRET" > "$SECRETS_PATH"
    chmod 600 "$SECRETS_PATH"
    chown "$SERVICE_USER" "$SECRETS_PATH"
    success "Generated secret key at $SECRETS_PATH"
else
    warn "Secrets file already exists at $SECRETS_PATH — not overwriting."
fi

# ---------------------------------------------------------------------------
# Step 6 — Python venv + package install
# ---------------------------------------------------------------------------
info "Creating Python venv at $VENV..."
sudo -u "$SERVICE_USER" python3 -m venv "$VENV"

info "Installing opalx-regsuite package (editable)..."
sudo -u "$SERVICE_USER" "$VENV/bin/pip" install --quiet --upgrade pip
sudo -u "$SERVICE_USER" "$VENV/bin/pip" install --quiet -e "$REPO_DIR"
success "Package installed."

REGSUITE_BIN="$VENV/bin/opalx-regsuite"

# ---------------------------------------------------------------------------
# Step 7 — Write config.toml
# ---------------------------------------------------------------------------
info "Writing $CONFIG_PATH..."
if [[ -f "$CONFIG_PATH" ]]; then
    warn "config.toml already exists — backing up to ${CONFIG_PATH}.bak"
    cp "$CONFIG_PATH" "${CONFIG_PATH}.bak"
fi

# Use opalx-regsuite init in non-interactive mode by passing all values via env/flags.
OPALX_REGSUITE_CONFIG="$CONFIG_PATH" \
sudo -u "$SERVICE_USER" \
    "$REGSUITE_BIN" init \
    --opalx-repo-root   "$OPALX_CLONE_DIR" \
    --builds-root       "$BUILDS_DIR" \
    --data-root         "$DATA_ROOT" \
    --regtests-repo-root "$REGTESTS_CLONE_DIR" \
    --regtests-branch   "master" \
    --default-branch    "master" \
    --default-arch      "cpu-serial" \
    --ssh-keys-dir      "$SSH_KEYS_DIR" \
    --config            "$CONFIG_PATH"

chown "$SERVICE_USER:$SERVICE_USER" "$CONFIG_PATH"
success "Config written to $CONFIG_PATH"

# ---------------------------------------------------------------------------
# Step 8 — Rebuild indexes from any existing run data
# ---------------------------------------------------------------------------
if [[ -d "$DATA_ROOT/runs" ]]; then
    info "Existing run data found — rebuilding indexes..."
    OPALX_REGSUITE_CONFIG="$CONFIG_PATH" \
    sudo -u "$SERVICE_USER" "$REGSUITE_BIN" rebuild-indexes --config "$CONFIG_PATH" \
        && success "Indexes rebuilt." \
        || warn "Index rebuild failed — you can run 'opalx-regsuite rebuild-indexes' manually later."
fi

# ---------------------------------------------------------------------------
# Step 9 — Systemd service
# ---------------------------------------------------------------------------
info "Installing systemd service..."

# Patch the service file's EnvironmentFile path in case /etc/opalx/secrets differs
SERVICE_SRC="$REPO_DIR/deploy/opalx-regsuite.service"
SERVICE_DEST="/etc/systemd/system/opalx-regsuite.service"

# Write a customised copy so that paths match this install
cat > "$SERVICE_DEST" <<EOF
[Unit]
Description=OPALX Regression Suite Web Server
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$HOME_DIR

# Sensitive values (mode 600, owned by $SERVICE_USER):
#   OPALX_SECRET_KEY=<256-bit hex>
EnvironmentFile=$SECRETS_PATH

Environment=OPALX_REGSUITE_CONFIG=$CONFIG_PATH

ExecStart=$VENV/bin/opalx-regsuite serve --host 0.0.0.0 --port 8000

Restart=on-failure
RestartSec=5s
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable opalx-regsuite
success "Service installed and enabled."

# ---------------------------------------------------------------------------
# Step 10 — First admin user
# ---------------------------------------------------------------------------
echo ""
info "Creating first admin user..."
echo "  You will be prompted for a username and password."
OPALX_REGSUITE_CONFIG="$CONFIG_PATH" \
sudo -u "$SERVICE_USER" "$REGSUITE_BIN" user-add --config "$CONFIG_PATH" \
    || warn "User creation failed or was skipped. Run 'opalx-regsuite user-add' manually."

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "========================================================"
echo "  OPALX Regression Suite — setup complete"
echo "========================================================"
echo ""
echo "  Directories:"
echo "    OPALX source     : $OPALX_CLONE_DIR"
echo "    Regression tests : $REGTESTS_CLONE_DIR"
echo "    Builds           : $BUILDS_DIR"
echo "    Test data        : $DATA_ROOT"
echo "    Config           : $CONFIG_PATH"
echo "    Secrets          : $SECRETS_PATH"
echo "    SSH keys         : $SSH_KEYS_DIR"
echo ""
echo "  Next steps:"
echo "    1. Review $CONFIG_PATH and adjust cmake_args, arch_configs, etc."
echo "    2. (Optional) Copy deploy/nginx.conf to /etc/nginx/sites-available/"
echo "       and update the server_name to match your domain/IP."
echo "    3. Start the service:  systemctl start opalx-regsuite"
echo "    4. Check status:       systemctl status opalx-regsuite"
echo "    5. View logs:          journalctl -u opalx-regsuite -f"
echo ""
echo "  The web UI will be available at http://<server-ip>:8000"
echo "========================================================"
