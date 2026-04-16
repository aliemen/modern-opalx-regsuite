"""Data models for per-user API keys.

Token format on the wire is:

    opalx_<prefix>_<secret>

where ``prefix`` is 8 base64url chars shown in the UI for recognition, and
``secret`` is ~43 base64url chars carrying 32 random bytes. Only the sha256
hash of the *entire* token is persisted server-side.
"""
from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


TOKEN_PREFIX = "opalx_"
"""Wire-format prefix used to tell API-key bearer tokens apart from JWTs."""

NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
"""Same shape as SSH-key names, so the two surfaces feel identical."""

MIN_EXPIRES_IN_DAYS = 1
MAX_EXPIRES_IN_DAYS = 3650
"""An upper bound (10 years) is cheap insurance against typos like ``999999``."""


class ApiKeyScope(str, Enum):
    """Fine-grained capabilities attachable to an API key.

    Kept intentionally narrow: today every key is scoped to SSH-key management
    only. Broader scopes would require auditing every other router before
    widening ``require_auth`` -> ``require_scoped``.
    """

    SSH_KEYS_READ = "ssh-keys:read"
    SSH_KEYS_WRITE = "ssh-keys:write"


ALL_SCOPES: tuple[ApiKeyScope, ...] = tuple(ApiKeyScope)


class ApiKeyRecord(BaseModel):
    """Persisted record in ``<user_dir>/api-keys.json``.

    ``secret_hash`` is ``hashlib.sha256(plaintext).hexdigest()`` of the full
    ``opalx_...`` token -- we never store the plaintext itself.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    prefix: str
    secret_hash: str
    scopes: list[ApiKeyScope]
    created_at: datetime
    last_used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None


class ApiKeyInfo(BaseModel):
    """Safe-to-return shape. Never contains ``secret_hash`` or plaintext."""

    id: str
    name: str
    prefix: str
    scopes: list[ApiKeyScope]
    created_at: datetime
    last_used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None

    @classmethod
    def from_record(cls, record: ApiKeyRecord) -> "ApiKeyInfo":
        return cls(
            id=record.id,
            name=record.name,
            prefix=record.prefix,
            scopes=list(record.scopes),
            created_at=record.created_at,
            last_used_at=record.last_used_at,
            expires_at=record.expires_at,
        )


class ApiKeyCreated(ApiKeyInfo):
    """Returned exactly once, when a key is created or rotated.

    The ``secret`` field carries the full ``opalx_...`` token. The client MUST
    store it; the server cannot recover it again.
    """

    secret: str


class ApiKeyCreateRequest(BaseModel):
    """Payload accepted by ``POST /api/settings/api-keys``."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=64)
    scopes: list[ApiKeyScope] = Field(..., min_length=1)
    expires_in_days: Optional[int] = Field(
        None,
        ge=MIN_EXPIRES_IN_DAYS,
        le=MAX_EXPIRES_IN_DAYS,
        description="If omitted, the key never expires.",
    )
