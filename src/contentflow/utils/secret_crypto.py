from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Integer, Text, column, select, table, update
from sqlalchemy.engine import Connection

from contentflow.config import settings


_SECRET_PREFIX = "cfsec:v1:"


def is_encrypted_secret(value: str | None) -> bool:
    return bool(value and value.startswith(_SECRET_PREFIX))


def _get_secret_material() -> str:
    return (settings.connector_secret_key or settings.api_secret_key or "").strip()


def has_secret_encryption_key() -> bool:
    return bool(_get_secret_material())


def _build_fernet() -> Fernet | None:
    secret_material = _get_secret_material()
    if not secret_material:
        return None
    digest = hashlib.sha256(secret_material.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret_value(value: str | None) -> str:
    raw_value = (value or "").strip()
    if not raw_value:
        return ""
    if is_encrypted_secret(raw_value):
        return raw_value
    fernet = _build_fernet()
    if fernet is None:
        return raw_value
    token = fernet.encrypt(raw_value.encode("utf-8")).decode("utf-8")
    return f"{_SECRET_PREFIX}{token}"


def decrypt_secret_value(value: str | None) -> str:
    raw_value = (value or "").strip()
    if not raw_value:
        return ""
    if not is_encrypted_secret(raw_value):
        return raw_value
    fernet = _build_fernet()
    if fernet is None:
        return ""
    token = raw_value[len(_SECRET_PREFIX):]
    try:
        return fernet.decrypt(token.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        return ""


def backfill_plaintext_project_integration_secrets(bind: Connection) -> int:
    integration_table = table(
        "project_integrations",
        column("id", Integer()),
        column("secret_value", Text()),
    )
    rows = bind.execute(
        select(integration_table.c.id, integration_table.c.secret_value).where(
            integration_table.c.secret_value.is_not(None),
            integration_table.c.secret_value != "",
        )
    ).fetchall()
    plaintext_rows = [
        (row.id, str(row.secret_value).strip())
        for row in rows
        if row.secret_value and not is_encrypted_secret(str(row.secret_value))
    ]
    if not plaintext_rows:
        return 0
    if not has_secret_encryption_key():
        raise RuntimeError(
            "CONNECTOR_SECRET_KEY 或 API_SECRET_KEY 必須存在，才能回填既有 connector secrets。"
        )

    for row_id, secret_value in plaintext_rows:
        bind.execute(
            update(integration_table)
            .where(integration_table.c.id == row_id)
            .values(secret_value=encrypt_secret_value(secret_value))
        )
    return len(plaintext_rows)