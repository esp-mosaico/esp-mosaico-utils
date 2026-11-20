"""Host-private pairing credentials, indexed by verified device identity."""
from __future__ import annotations

import contextlib
import json
import os
import pathlib
import re
import tempfile
import time


def validate_token(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-fA-F]{64}", value) is None:
        raise ValueError("pairing token must be 64 hexadecimal characters")
    return value.lower()


class PairingStore:
    def __init__(self, root: pathlib.Path) -> None:
        self.root = root

    def _path(self, device_id: str) -> pathlib.Path:
        if re.fullmatch(r"[0-9a-f]{32}", device_id) is None:
            raise ValueError("invalid pairing Device ID")
        return self.root / (device_id + ".json")

    def get(self, device_id: str) -> str | None:
        path = self._path(device_id)
        try:
            if self.root.is_symlink() or path.is_symlink():
                raise ValueError("pairing credential must not be a symbolic link")
            saved = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(saved, dict):
                raise TypeError("invalid saved pairing credential")
            if saved.get("device_id") != device_id:
                raise ValueError("pairing credential identity mismatch")
            if os.name != "nt" and (path.stat().st_mode & 0o077 or self.root.stat().st_mode & 0o077):
                raise PermissionError("pairing credentials require private directory/file permissions")
            return validate_token(saved["token"])
        except FileNotFoundError:
            return None
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise ValueError("invalid saved pairing credential") from error

    def remember(self, device_id: str, token: str) -> None:
        path = self._path(device_id)
        token = validate_token(token)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.root.is_symlink():
            raise ValueError("pairing directory must not be a symbolic link")
        if os.name != "nt":
            self.root.chmod(0o700)
        fd, temporary = tempfile.mkstemp(prefix=".pairing-", dir=str(self.root))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"device_id": device_id, "token": token, "paired_ns": time.time_ns()}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary)

    def forget(self, device_id: str) -> None:
        with contextlib.suppress(FileNotFoundError):
            self._path(device_id).unlink()

    def devices(self) -> list[str]:
        # Inventory never returns a credential or copies it to project diagnostics.
        return sorted(path.stem for path in self.root.glob("*.json")
                      if re.fullmatch(r"[0-9a-f]{32}", path.stem) and self.get(path.stem))
