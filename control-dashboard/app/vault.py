"""
OpenML Vault — multiple independently-encrypted vaults, each holding secrets
scoped either 'global' or to a named project.

Envelope encryption ("one data key, many locks"), per vault:
  * A random 256-bit Data Encryption Key (DEK) encrypts every secret value
    (AES-256-GCM). The DEK is NEVER stored in plaintext.
  * The DEK is wrapped independently by multiple "key slots" — any one unlocks:
       passphrase | code | recovery | auto (machine key file)
  * Sealed = that vault's DEK not in memory. Each vault seals/unlocks on its own.

Scope: a secret belongs to a vault and has a scope = 'global' (all projects) or
a project name. Storage is the existing Postgres; DEKs only live in this process.
"""
from __future__ import annotations

import base64
import contextlib
import json
import os
import secrets
import time
from typing import Optional

import psycopg2
from argon2.low_level import Type, hash_secret_raw
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

PG_DSN = os.environ.get("OPENML_PG_DSN", "")
AUTO_DIR = os.environ.get("OPENML_VAULT_AUTODIR", "/vault")

# vault_id -> DEK, only for currently-unlocked vaults
_DEKS: dict[int, bytes] = {}
_UNDELETABLE = {"recovery"}
_BACKUP_MAGIC = b"OMLV1"


# --------------------------------------------------------------------------- #
# crypto helpers
# --------------------------------------------------------------------------- #
def _kek(credential: str, salt: bytes) -> bytes:
    return hash_secret_raw(credential.encode(), salt, time_cost=3,
                           memory_cost=64 * 1024, parallelism=2, hash_len=32, type=Type.ID)


def _wrap(key: bytes, data: bytes) -> str:
    n = secrets.token_bytes(12)
    return base64.b64encode(n + AESGCM(key).encrypt(n, data, None)).decode()


def _unwrap(key: bytes, blob: str) -> bytes:
    raw = base64.b64decode(blob)
    return AESGCM(key).decrypt(raw[:12], raw[12:], None)


def _enc(dek: bytes, text: str) -> str:
    n = secrets.token_bytes(12)
    return base64.b64encode(n + AESGCM(dek).encrypt(n, text.encode(), None)).decode()


def _dec(dek: bytes, blob: str) -> str:
    raw = base64.b64decode(blob)
    return AESGCM(dek).decrypt(raw[:12], raw[12:], None).decode()


# --------------------------------------------------------------------------- #
# storage / schema (with one-time migration from the old single-vault schema)
# --------------------------------------------------------------------------- #
@contextlib.contextmanager
def _tx():
    conn = psycopg2.connect(PG_DSN)
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    finally:
        conn.close()


def _init_schema() -> None:
    with _tx() as cur:
        cur.execute("SELECT to_regclass('public.vaults')")
        if cur.fetchone()[0] is not None:
            return
        # The old single-vault tables (if any) are empty at this point — replace
        # them with the multi-vault schema.
        cur.execute("""
        DROP TABLE IF EXISTS vault_slots, vault_secrets, vault_meta, vault_audit CASCADE;
        CREATE TABLE vaults(
            id serial PRIMARY KEY, name text UNIQUE NOT NULL,
            created double precision, auto_unseal boolean DEFAULT false);
        CREATE TABLE vault_slots(
            id serial PRIMARY KEY,
            vault_id int REFERENCES vaults(id) ON DELETE CASCADE,
            kind text, label text, salt text, wrapped text, created double precision);
        CREATE TABLE vault_secrets(
            vault_id int REFERENCES vaults(id) ON DELETE CASCADE,
            scope text, name text, value text, updated double precision,
            PRIMARY KEY(vault_id, scope, name));
        CREATE TABLE vault_audit(
            id serial PRIMARY KEY, vault_id int, ts double precision,
            action text, detail text);
        """)


def _audit(cur, vid: int, action: str, detail: str = "") -> None:
    cur.execute("INSERT INTO vault_audit(vault_id,ts,action,detail) VALUES(%s,%s,%s,%s)",
                (vid, time.time(), action, detail))


def _add_slot(cur, vid: int, kind: str, label: str, credential: str, dek: bytes) -> None:
    salt = secrets.token_bytes(16)
    cur.execute(
        "INSERT INTO vault_slots(vault_id,kind,label,salt,wrapped,created) VALUES(%s,%s,%s,%s,%s,%s)",
        (vid, kind, label, base64.b64encode(salt).decode(),
         _wrap(_kek(credential, salt), dek), time.time()))


def _dek(vid: int) -> bytes:
    d = _DEKS.get(vid)
    if d is None:
        raise ValueError("vault is sealed — unlock it first")
    return d


def _auto_file(vid: int) -> str:
    return os.path.join(AUTO_DIR, f"auto_{vid}.key")


# --------------------------------------------------------------------------- #
# vaults
# --------------------------------------------------------------------------- #
def status() -> dict:
    try:
        _init_schema()
        return {"ok": True, "vaults": list_vaults()}
    except Exception as e:
        return {"ok": False, "error": str(e), "vaults": []}


def list_vaults() -> list:
    _init_schema()
    with _tx() as cur:
        cur.execute("""
            SELECT v.id, v.name, v.auto_unseal, count(s.*)
            FROM vaults v LEFT JOIN vault_secrets s ON s.vault_id = v.id
            GROUP BY v.id ORDER BY v.id""")
        rows = cur.fetchall()
    return [{"id": i, "name": n, "unsealed": i in _DEKS,
             "auto_unseal": bool(a), "secrets": c} for i, n, a, c in rows]


def create_vault(name: str, passphrase: str) -> dict:
    _init_schema()
    name = (name or "").strip()
    if not name:
        raise ValueError("vault name required")
    with _tx() as cur:
        cur.execute("SELECT 1 FROM vaults WHERE name=%s", (name,))
        if cur.fetchone():
            raise ValueError(f"a vault named '{name}' already exists")
        cur.execute("INSERT INTO vaults(name,created,auto_unseal) VALUES(%s,%s,false) RETURNING id",
                    (name, time.time()))
        vid = cur.fetchone()[0]
        dek = secrets.token_bytes(32)
        recovery = base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
        _add_slot(cur, vid, "passphrase", "project passphrase", passphrase, dek)
        _add_slot(cur, vid, "recovery", "recovery kit", recovery, dek)
        _audit(cur, vid, "create", f"vault '{name}' created")
    _DEKS[vid] = dek
    return {"id": vid, "name": name, "recovery_key": recovery}


def delete_vault(vid: int) -> None:
    with _tx() as cur:
        cur.execute("DELETE FROM vaults WHERE id=%s", (vid,))
    _DEKS.pop(vid, None)
    with contextlib.suppress(FileNotFoundError):
        os.remove(_auto_file(vid))


def unlock(vid: int, credential: str) -> bool:
    with _tx() as cur:
        cur.execute("SELECT salt,wrapped,kind FROM vault_slots WHERE vault_id=%s", (vid,))
        rows = cur.fetchall()
    for salt_b64, wrapped, kind in rows:
        try:
            dek = _unwrap(_kek(credential, base64.b64decode(salt_b64)), wrapped)
        except Exception:
            continue
        _DEKS[vid] = dek
        with _tx() as cur:
            _audit(cur, vid, "unlock", f"via {kind}")
        return True
    with _tx() as cur:
        _audit(cur, vid, "unlock_fail", "bad credential")
    return False


def lock(vid: int) -> None:
    _DEKS.pop(vid, None)


# --------------------------------------------------------------------------- #
# key slots
# --------------------------------------------------------------------------- #
def add_code(vid: int, label: str, code: str) -> None:
    dek = _dek(vid)
    with _tx() as cur:
        _add_slot(cur, vid, "code", label or "access code", code, dek)
        _audit(cur, vid, "add_code", label)


def list_slots(vid: int) -> list:
    with _tx() as cur:
        cur.execute("SELECT id,kind,label,created FROM vault_slots WHERE vault_id=%s ORDER BY id", (vid,))
        return [{"id": i, "kind": k, "label": l, "created": c} for i, k, l, c in cur.fetchall()]


def remove_slot(vid: int, slot_id: int) -> None:
    _dek(vid)
    with _tx() as cur:
        cur.execute("SELECT kind FROM vault_slots WHERE id=%s AND vault_id=%s", (slot_id, vid))
        row = cur.fetchone()
        if not row:
            raise ValueError("no such slot")
        if row[0] in _UNDELETABLE:
            raise ValueError("the recovery slot can't be removed")
        cur.execute("SELECT count(*) FROM vault_slots WHERE vault_id=%s AND kind='passphrase'", (vid,))
        if row[0] == "passphrase" and cur.fetchone()[0] <= 1:
            raise ValueError("can't remove the only passphrase slot")
        cur.execute("DELETE FROM vault_slots WHERE id=%s", (slot_id,))
        _audit(cur, vid, "remove_slot", str(slot_id))


def change_passphrase(vid: int, new_passphrase: str) -> None:
    dek = _dek(vid)
    with _tx() as cur:
        cur.execute("DELETE FROM vault_slots WHERE vault_id=%s AND kind='passphrase'", (vid,))
        _add_slot(cur, vid, "passphrase", "project passphrase", new_passphrase, dek)
        _audit(cur, vid, "change_passphrase", "")


# --------------------------------------------------------------------------- #
# secrets (scope = 'global' or a project name)
# --------------------------------------------------------------------------- #
def set_secret(vid: int, scope: str, name: str, value: str) -> None:
    dek = _dek(vid)
    scope = (scope or "global").strip() or "global"
    with _tx() as cur:
        cur.execute(
            "INSERT INTO vault_secrets(vault_id,scope,name,value,updated) VALUES(%s,%s,%s,%s,%s) "
            "ON CONFLICT (vault_id,scope,name) DO UPDATE SET value=EXCLUDED.value, updated=EXCLUDED.updated",
            (vid, scope, name, _enc(dek, value), time.time()))
        _audit(cur, vid, "set", f"{scope}/{name}")


def get_secret(vid: int, scope: str, name: str) -> Optional[str]:
    dek = _dek(vid)
    with _tx() as cur:
        cur.execute("SELECT value FROM vault_secrets WHERE vault_id=%s AND scope=%s AND name=%s",
                    (vid, scope, name))
        row = cur.fetchone()
        if not row:
            return None
        _audit(cur, vid, "get", f"{scope}/{name}")
    return _dec(dek, row[0])


def list_secrets(vid: int, scope: Optional[str] = None) -> list:
    _dek(vid)
    with _tx() as cur:
        if scope:
            cur.execute("SELECT scope,name,updated FROM vault_secrets WHERE vault_id=%s AND scope=%s ORDER BY name",
                        (vid, scope))
        else:
            cur.execute("SELECT scope,name,updated FROM vault_secrets WHERE vault_id=%s ORDER BY scope,name", (vid,))
        return [{"scope": s, "name": n, "updated": u} for s, n, u in cur.fetchall()]


def list_scopes(vid: int) -> list:
    _dek(vid)
    with _tx() as cur:
        cur.execute("SELECT DISTINCT scope FROM vault_secrets WHERE vault_id=%s ORDER BY scope", (vid,))
        return [r[0] for r in cur.fetchall()]


def delete_secret(vid: int, scope: str, name: str) -> None:
    _dek(vid)
    with _tx() as cur:
        cur.execute("DELETE FROM vault_secrets WHERE vault_id=%s AND scope=%s AND name=%s", (vid, scope, name))
        _audit(cur, vid, "delete", f"{scope}/{name}")


# --------------------------------------------------------------------------- #
# auto-unseal (per vault)
# --------------------------------------------------------------------------- #
def set_auto_unseal(vid: int, enabled: bool) -> None:
    dek = _dek(vid)
    with _tx() as cur:
        cur.execute("DELETE FROM vault_slots WHERE vault_id=%s AND kind='auto'", (vid,))
        if enabled:
            key = base64.b64encode(secrets.token_bytes(32)).decode()
            os.makedirs(AUTO_DIR, exist_ok=True)
            with open(_auto_file(vid), "w") as f:
                f.write(key)
            os.chmod(_auto_file(vid), 0o600)
            _add_slot(cur, vid, "auto", "auto-unseal key file", key, dek)
        else:
            with contextlib.suppress(FileNotFoundError):
                os.remove(_auto_file(vid))
        cur.execute("UPDATE vaults SET auto_unseal=%s WHERE id=%s", (enabled, vid))
        _audit(cur, vid, "auto_unseal", "on" if enabled else "off")


def try_auto_unseal() -> int:
    """On startup, auto-unseal every vault that has a key file. Returns count."""
    n = 0
    try:
        for v in list_vaults():
            f = _auto_file(v["id"])
            if os.path.exists(f):
                with open(f) as fh:
                    if unlock(v["id"], fh.read().strip()):
                        n += 1
    except Exception:
        pass
    return n


# --------------------------------------------------------------------------- #
# backup / restore / reset
# --------------------------------------------------------------------------- #
def export_secrets(vid: int, backup_password: str) -> str:
    dek = _dek(vid)
    with _tx() as cur:
        cur.execute("SELECT scope,name,value FROM vault_secrets WHERE vault_id=%s", (vid,))
        items = [{"scope": s, "name": n, "value": _dec(dek, v)} for s, n, v in cur.fetchall()]
    salt, n = secrets.token_bytes(16), secrets.token_bytes(12)
    ct = AESGCM(_kek(backup_password, salt)).encrypt(
        n, json.dumps({"version": 1, "secrets": items}).encode(), None)
    with _tx() as cur:
        _audit(cur, vid, "export", f"{len(items)} secrets")
    return base64.b64encode(_BACKUP_MAGIC + salt + n + ct).decode()


def import_secrets(vid: int, backup_password: str, blob: str) -> int:
    _dek(vid)
    try:
        raw = base64.b64decode(blob)
    except Exception:
        raise ValueError("not a valid backup")
    if raw[:5] != _BACKUP_MAGIC:
        raise ValueError("not an OpenML vault backup")
    salt, n, ct = raw[5:21], raw[21:33], raw[33:]
    try:
        payload = AESGCM(_kek(backup_password, salt)).decrypt(n, ct, None)
    except Exception:
        raise ValueError("wrong backup password or corrupt backup")
    count = 0
    for it in json.loads(payload).get("secrets", []):
        set_secret(vid, it["scope"], it["name"], it["value"])
        count += 1
    with _tx() as cur:
        _audit(cur, vid, "import", f"{count} secrets")
    return count
