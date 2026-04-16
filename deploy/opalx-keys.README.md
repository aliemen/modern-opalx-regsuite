# opalx-keys.sh - Scripted SSH key rotation for the OPALX Regression Suite

A small bash client that talks to your Regression Suite's SSH-key endpoints
with a scoped API token. Use it to automate key rotation from a laptop (for
example, behind a keyboard macro) instead of clicking through the web UI.

---

## Overview

The regsuite already exposes `/api/settings/ssh-keys` for the web UI. This
script calls the same endpoints with a long-lived, scope-limited bearer
token, so you can:

* list the SSH keys currently registered on the server,
* upload a new key,
* replace an existing key (ideal for short-lived credentials, e.g. a daily
  CSCS Daint key),
* delete a key that is not referenced by any connection.

API keys are scoped to the SSH-key endpoints only. A leaked token cannot
read run data, touch your connections, or mint new API keys.

---

## Prerequisites

* `bash` 3.2+ (the script is macOS-safe; no `mapfile`, no bash-4-only
  features).
* `curl` - preinstalled on macOS and every mainstream Linux.
* `jq` - `brew install jq` or `apt install jq`.

---

## Setup

### 1. Mint an API key in the web UI

1. Log in to your regsuite server.
2. Go to **Settings -> API keys -> New API key**.
3. Name it something identifying (`macbook`, `ci-runner`, ...). Leave both
   scopes checked. Pick an expiry that matches your rotation cadence.
4. **Copy the token immediately.** It starts with `opalx_...` and is shown
   exactly once - the server keeps only a hash.

### 2. Write the credentials file

```bash
mkdir -p ~/.config/opalx-regsuite
cat > ~/.config/opalx-regsuite/credentials <<'EOF'
OPALX_API_URL="https://opalx.example.com"
OPALX_API_TOKEN="opalx_yourPrefix_yourSecret..."
EOF
chmod 600 ~/.config/opalx-regsuite/credentials
```

The `chmod 600` is mandatory - the script refuses to run if the file is
group- or world-readable.

### 3. Drop the script somewhere on `$PATH`

```bash
cp deploy/opalx-keys.sh ~/.local/bin/opalx-keys
chmod +x ~/.local/bin/opalx-keys
```

Or call it from wherever you cloned the repo.

---

## Common workflows

### List your keys

```bash
opalx-keys list
```

### Upload a fresh key

```bash
ssh-keygen -t ed25519 -f ./macbook_id -N ''
opalx-keys upload macbook ./macbook_id
```

You still need to add the corresponding **public** key (`macbook_id.pub`) to
`~/.ssh/authorized_keys` on any host your regsuite connections target - the
regsuite stores your private half, not the other side of the pair.

### Rotate a short-lived key (e.g. daily Daint)

```bash
# Fetch / regenerate the credential you got from CSCS, then:
opalx-keys replace cscs-key /path/to/new-cscs-key \
    --cert /path/to/new-cscs-key-cert.pub
```

`replace` preserves the key's name on the server, so every connection that
already references it picks up the new credentials on the next run - no
unlink/relink dance required.

### Delete a key

```bash
opalx-keys delete macbook
```

Fails with exit code 3 if any of your connections still reference the key.
Unlink them in the UI (or redirect them to a different key) first.

---

## Keyboard macro example (macOS)

A minimal Automator / Raycast script:

```bash
#!/usr/bin/env bash
set -e
NEW_KEY="$(mktemp -d)/cscs-key"
# ... produce the new key at $NEW_KEY ...
/usr/local/bin/opalx-keys replace cscs-key "$NEW_KEY" \
    --cert "${NEW_KEY}-cert.pub"
rm -rf "$(dirname "$NEW_KEY")"
```

Bind the macro to a hotkey, and your daily Daint key refresh becomes a
one-keystroke operation.

---

## Security notes

* **Store the token exactly once** in `~/.config/opalx-regsuite/credentials`.
  Keep the file at `0600`. The script enforces this on startup.
* **Revoke on leak.** Open **Settings -> API keys** and click the trash
  icon next to the compromised key. Old token stops working immediately -
  the server wipes the hash from its in-memory index.
* **Rotate periodically.** Click the refresh icon to mint a new secret
  under the same key id. Distribute the new secret to every client that
  used the old one.
* **Never commit the token.** Treat it like a password; the entropy is
  equivalent to a 256-bit secret.
* **HTTPS only in production.** The script is transport-agnostic, but
  passing a bearer token over plain HTTP is dangerous. Put nginx in front.

---

## Exit codes

| Code | Meaning                                    |
|:----:|--------------------------------------------|
| 0    | Success                                    |
| 1    | Generic / network / usage error            |
| 2    | 401 - token missing, invalid, or expired   |
| 3    | 400 / 409 / 422 - validation / conflict    |
| 4    | 404 - key name does not exist              |
| 5    | 403 - token lacks the required scope       |

Use these in shell pipelines / CI to differentiate "I need to rotate my
token" (2) from "the key I tried to delete is in use" (3 with message).

---

## Troubleshooting

**"OPALX_API_TOKEN does not start with 'opalx_'"**
You pasted a JWT from the web UI's developer tools, not an API key. Mint an
API key at **Settings -> API keys**.

**`[401] Invalid or expired API key`**
Token revoked, rotated, or expired. Re-mint in the UI and update the
credentials file.

**`[403] API key missing required scope(s): ssh-keys:write`**
You created a read-only key but tried to upload / replace / delete. Rotate
the key's scopes by creating a new key with the right set and revoking the
old one.

**`[409] Key 'foo' is in use by connection(s): daint-cpu. Unlink them first.`**
The connection references this key by name. Edit the connection to point at
a different key before deleting.

**`Credentials file ... has mode 644`**
Run `chmod 600 ~/.config/opalx-regsuite/credentials`. The script refuses
to source a token from a world-readable file.

---

## Related

* [README.md](../README.md) - full Regression Suite documentation.
* `Settings -> API keys` in the web UI - mint, rotate, and revoke tokens.
* `Settings -> SSH keys` - manual equivalent of what this script automates.
