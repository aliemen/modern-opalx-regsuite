"""Per-user API keys for scripted access to SSH-key management endpoints.

Split into focused submodules:

* :mod:`.models`   -- pydantic records + scope enum + the bearer-token format.
* :mod:`.store`    -- per-user JSON persistence (``api-keys.json``).
* :mod:`.index`    -- process-wide, in-memory ``sha256 -> (user, id)`` index.
* :mod:`.service`  -- high-level create / verify / rotate / revoke.

API keys authenticate only against the SSH-keys router; see
:func:`..api.deps.require_scoped`.
"""
from .models import ApiKeyCreated, ApiKeyInfo, ApiKeyRecord, ApiKeyScope, TOKEN_PREFIX
from . import index, service, store

__all__ = [
    "ApiKeyCreated",
    "ApiKeyInfo",
    "ApiKeyRecord",
    "ApiKeyScope",
    "TOKEN_PREFIX",
    "index",
    "service",
    "store",
]
