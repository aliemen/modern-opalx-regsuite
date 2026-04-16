#!/usr/bin/env bash
# opalx-keys.sh - Manage SSH keys on an OPALX Regression Suite server from
# the command line, using a per-user scoped API key (created once in the web
# UI at Settings -> API keys).
#
# See deploy/opalx-keys.README.md for a full manual.
set -euo pipefail

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
# printf rather than `echo -e` -- macOS ships bash 3.2 whose /bin/echo does
# not interpret \e, and we want portable escape handling.
info()    { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
success() { printf '\033[1;32m  v\033[0m %s\n' "$*"; }
warn()    { printf '\033[1;33m  !\033[0m %s\n' "$*"; }
die()     { local code="${2:-1}"; printf '\033[1;31m[ERROR]\033[0m %s\n' "$1" >&2; exit "$code"; }

# Exit codes (surfaced in scripts / CI):
#   0  success
#   1  generic / usage / network
#   2  auth (401)
#   3  validation / conflict (400, 409, 422)
#   4  not found (404)
#   5  forbidden (403, e.g. wrong scope)

# Map HTTP status -> exit code for automation-friendly error handling.
http_to_exit() {
    case "$1" in
        401) echo 2 ;;
        403) echo 5 ;;
        404) echo 4 ;;
        400|409|422) echo 3 ;;
        *) echo 1 ;;
    esac
}

# ---------------------------------------------------------------------------
# Credential resolution
# ---------------------------------------------------------------------------
CREDS_FILE_DEFAULT="${HOME}/.config/opalx-regsuite/credentials"
CREDS_FILE="${OPALX_CREDENTIALS_FILE:-$CREDS_FILE_DEFAULT}"

load_credentials_file() {
    [[ -f "$CREDS_FILE" ]] || return 0

    # Refuse to source a file other users can read -- the token is secret.
    # macOS `stat -f %A` and Linux `stat -c %a` both yield a numeric mode.
    local mode
    if mode=$(stat -f %Lp "$CREDS_FILE" 2>/dev/null); then
        :
    elif mode=$(stat -c %a "$CREDS_FILE" 2>/dev/null); then
        :
    else
        mode=""
    fi
    if [[ -n "$mode" && "$mode" != "600" && "$mode" != "400" ]]; then
        die "Credentials file $CREDS_FILE has mode $mode. Run: chmod 600 $CREDS_FILE" 1
    fi

    # Source in a subshell-free fashion: the file is a shell-sourceable
    # key=value document with optional quotes. We only ever read known names.
    # shellcheck disable=SC1090
    source "$CREDS_FILE"
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
API_URL=""
API_TOKEN=""
CERT_FILE=""

usage() {
    cat <<'EOF'
Usage: opalx-keys.sh <command> [options]

Commands:
  list                                       List your SSH keys on the server
  upload <name> <private-key-path> [opts]    Upload a new SSH key
  replace <name> <private-key-path> [opts]   Replace an existing SSH key
  delete <name>                              Delete an SSH key

Common options:
  -u, --url URL            Server base URL     (env: OPALX_API_URL)
  -t, --token TOKEN        API token           (env: OPALX_API_TOKEN)
  -c, --cert FILE          SSH certificate file (upload/replace only)
  -h, --help               Show this help

Credential resolution order (highest wins):
  1. --url / --token CLI flags
  2. OPALX_API_URL / OPALX_API_TOKEN environment variables
  3. ~/.config/opalx-regsuite/credentials   (chmod 600, shell-sourceable)

Example credentials file:
  OPALX_API_URL="https://opalx.example.com"
  OPALX_API_TOKEN="opalx_ab12CD_secret..."

Exit codes:
  0 success | 1 generic/network | 2 auth (401) | 3 validation (400/409/422)
  4 not found (404) | 5 forbidden (403, wrong scope)
EOF
}

if [[ $# -lt 1 ]]; then
    usage
    exit 1
fi

# Short-circuit help requests BEFORE we try to load credentials, so that
# `opalx-keys.sh --help` works the very first time the script is run.
case "$1" in
    -h|--help|help)
        usage
        exit 0
        ;;
esac

CMD="$1"
shift

# Collect positionals after flag stripping.
POS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        -u|--url)   API_URL="$2";   shift 2 ;;
        -t|--token) API_TOKEN="$2"; shift 2 ;;
        -c|--cert)  CERT_FILE="$2"; shift 2 ;;
        -h|--help)  usage; exit 0 ;;
        --)         shift; POS+=("$@"); break ;;
        -*)         die "Unknown option: $1" 1 ;;
        *)          POS+=("$1"); shift ;;
    esac
done

# Pre-flight: required tools.
command -v curl >/dev/null 2>&1 || die "curl is required but not installed." 1
command -v jq   >/dev/null 2>&1 || die "jq is required. Install with 'brew install jq' or 'apt install jq'." 1

load_credentials_file
API_URL="${API_URL:-${OPALX_API_URL:-}}"
API_TOKEN="${API_TOKEN:-${OPALX_API_TOKEN:-}}"

# Strip a trailing slash so URL concatenation stays single-slash clean.
API_URL="${API_URL%/}"

[[ -n "$API_URL"   ]] || die "Server URL is unset. Use --url, OPALX_API_URL, or put it in $CREDS_FILE" 1
[[ -n "$API_TOKEN" ]] || die "API token is unset. Use --token, OPALX_API_TOKEN, or put it in $CREDS_FILE" 1

# Sanity-check the token shape. Wrong-type credentials trip a 401 on the
# server but this check surfaces the problem locally with a clearer message.
if [[ "$API_TOKEN" != opalx_* ]]; then
    warn "OPALX_API_TOKEN does not start with 'opalx_' - that looks like a JWT, not an API key. Mint one at Settings -> API keys."
fi

# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------
# Run curl and split body from status into two shell values. Returns 0 on
# 2xx, non-zero via http_to_exit() otherwise. Always prints server-provided
# `detail` on failure.
call_api() {
    local method="$1"; shift
    local path="$1";   shift

    # Inline cleanup instead of `trap RETURN` -- with `set -u`, trapping on
    # RETURN fires in the caller's scope where `tmp_body` is already
    # out-of-scope (local vars die with the function).
    local tmp_body; tmp_body=$(mktemp)

    local http_code
    http_code=$(
        curl -sS \
            -o "$tmp_body" \
            -w "%{http_code}" \
            -X "$method" \
            -H "Authorization: Bearer $API_TOKEN" \
            -H "Accept: application/json" \
            "$@" \
            "${API_URL}${path}"
    ) || { rm -f "$tmp_body"; die "Network error contacting ${API_URL}${path}" 1; }

    if [[ "$http_code" -ge 200 && "$http_code" -lt 300 ]]; then
        cat "$tmp_body"
        rm -f "$tmp_body"
        return 0
    fi

    # Surface server-provided detail if it is JSON, otherwise print raw body.
    local detail
    if detail=$(jq -er '.detail // empty' "$tmp_body" 2>/dev/null) && [[ -n "$detail" ]]; then
        printf '\033[1;31m[%s]\033[0m %s\n' "$http_code" "$detail" >&2
    else
        printf '\033[1;31m[%s]\033[0m %s\n' "$http_code" "$(cat "$tmp_body")" >&2
    fi
    rm -f "$tmp_body"
    exit "$(http_to_exit "$http_code")"
}

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
cmd_list() {
    local body; body=$(call_api GET "/api/settings/ssh-keys")
    local n; n=$(echo "$body" | jq 'length')
    if [[ "$n" -eq 0 ]]; then
        info "No SSH keys registered on the server."
        return 0
    fi
    info "SSH keys ($n):"
    echo "$body" | jq -r '.[] | "  - \(.name)\t\(.fingerprint // "-")\t\(.created_at)"' \
        | column -t -s $'\t'
}

cmd_upload() {
    [[ ${#POS[@]} -ge 2 ]] || die "Usage: opalx-keys.sh upload <name> <private-key-path>" 1
    local name="${POS[0]}"
    local keyfile="${POS[1]}"

    [[ -f "$keyfile" ]] || die "Key file not found: $keyfile" 1

    local form_args=( -F "name=$name" -F "key_file=@${keyfile}" )
    if [[ -n "$CERT_FILE" ]]; then
        [[ -f "$CERT_FILE" ]] || die "Certificate file not found: $CERT_FILE" 1
        form_args+=( -F "cert_file=@${CERT_FILE}" )
    fi

    info "Uploading key '$name' from $keyfile..."
    local body; body=$(call_api POST "/api/settings/ssh-keys" "${form_args[@]}")
    local fp;   fp=$(echo "$body" | jq -r '.fingerprint // "-"')
    success "Uploaded '$name' (fingerprint: $fp)."
}

cmd_replace() {
    [[ ${#POS[@]} -ge 2 ]] || die "Usage: opalx-keys.sh replace <name> <private-key-path>" 1
    local name="${POS[0]}"
    local keyfile="${POS[1]}"

    [[ -f "$keyfile" ]] || die "Key file not found: $keyfile" 1

    local form_args=( -F "key_file=@${keyfile}" )
    if [[ -n "$CERT_FILE" ]]; then
        [[ -f "$CERT_FILE" ]] || die "Certificate file not found: $CERT_FILE" 1
        form_args+=( -F "cert_file=@${CERT_FILE}" )
    fi

    info "Replacing key '$name' with contents of $keyfile..."
    # URL-encode the name to handle hyphens safely (rare, but cheap insurance).
    local enc_name; enc_name=$(jq -rn --arg n "$name" '$n|@uri')
    local body; body=$(call_api PUT "/api/settings/ssh-keys/${enc_name}" "${form_args[@]}")
    local fp;   fp=$(echo "$body" | jq -r '.fingerprint // "-"')
    success "Replaced '$name' (fingerprint: $fp)."
}

cmd_delete() {
    [[ ${#POS[@]} -ge 1 ]] || die "Usage: opalx-keys.sh delete <name>" 1
    local name="${POS[0]}"
    local enc_name; enc_name=$(jq -rn --arg n "$name" '$n|@uri')

    info "Deleting key '$name'..."
    call_api DELETE "/api/settings/ssh-keys/${enc_name}" >/dev/null
    success "Deleted '$name'."
}

case "$CMD" in
    list)    cmd_list ;;
    upload)  cmd_upload ;;
    replace) cmd_replace ;;
    delete)  cmd_delete ;;
    help|-h|--help) usage ;;
    *) usage; die "Unknown command: $CMD" 1 ;;
esac
