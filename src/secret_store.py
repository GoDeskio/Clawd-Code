"""Store channel and device secrets in the OS keyring, or in an encrypted file.

The file fallback is used when the keyring library is missing or refuses the
write. Tokens are never written into settings JSON and never logged here.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path

_SERVICE = "jonathan-ai"


def _chmod(path: Path, mode: int) -> None:
    try:
        path.chmod(mode)
    except OSError:
        return


def _keyring():
    choice = os.environ.get("JONATHAN_SECRET_BACKEND", "auto").strip().lower()
    if choice == "file":
        return None
    try:
        import keyring
    except Exception:
        return None
    if choice == "keyring":
        return keyring
    try:
        keyring.get_password(_SERVICE, "jonathan-probe")
    except Exception:
        return None
    return keyring


def _account(user_id: str, name: str) -> str:
    return f"{user_id}:{name}"


def _key_path(directory: Path, user_id: str) -> Path:
    return directory / f"key-{user_id}.bin"


def _secret_path(directory: Path, user_id: str, name: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name)
    return directory / f"secret-{user_id}-{safe}.bin"


def _load_key(directory: Path, user_id: str) -> bytes:
    directory.mkdir(parents=True, exist_ok=True)
    _chmod(directory, 0o700)
    path = _key_path(directory, user_id)
    if path.is_file():
        return path.read_bytes()
    key = os.urandom(32)
    path.write_bytes(key)
    _chmod(path, 0o600)
    return key


def _keystream(key: bytes, nonce: bytes, size: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < size:
        block = hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:size])


def _seal(key: bytes, plaintext: str) -> bytes:
    nonce = os.urandom(16)
    raw = plaintext.encode("utf-8")
    body = bytes(a ^ b for a, b in zip(raw, _keystream(key, nonce, len(raw))))
    mac = hmac.new(key, nonce + body, hashlib.sha256).digest()
    return nonce + mac + body


def _open_sealed(key: bytes, blob: bytes) -> str:
    if len(blob) < 48:
        raise ValueError("secret file is unreadable")
    nonce, mac, body = blob[:16], blob[16:48], blob[48:]
    expected = hmac.new(key, nonce + body, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expected):
        raise ValueError("secret file failed its check")
    raw = bytes(a ^ b for a, b in zip(body, _keystream(key, nonce, len(body))))
    return raw.decode("utf-8")


def put_secret(
    directory: Path,
    user_id: str,
    name: str,
    value: str,
    *,
    backend: object | None = None,
) -> None:
    """Save one secret. A blank value does not erase a secret already stored."""
    text = value.strip()
    if not text:
        return
    ring = backend if backend is not None else _keyring()
    if ring is not None:
        ring.set_password(_SERVICE, _account(user_id, name), text)
        path = _secret_path(directory, user_id, name)
        if path.is_file():
            path.unlink()
        return
    directory.mkdir(parents=True, exist_ok=True)
    _chmod(directory, 0o700)
    path = _secret_path(directory, user_id, name)
    path.write_bytes(_seal(_load_key(directory, user_id), text))
    _chmod(path, 0o600)


def get_secret(
    directory: Path,
    user_id: str,
    name: str,
    *,
    backend: object | None = None,
) -> str:
    ring = backend if backend is not None else _keyring()
    if ring is not None:
        found = ring.get_password(_SERVICE, _account(user_id, name))
        if isinstance(found, str) and found:
            return found
    path = _secret_path(directory, user_id, name)
    if not path.is_file():
        return ""
    return _open_sealed(_load_key(directory, user_id), path.read_bytes())


def has_secret(
    directory: Path,
    user_id: str,
    name: str,
    *,
    backend: object | None = None,
) -> bool:
    return bool(get_secret(directory, user_id, name, backend=backend))
