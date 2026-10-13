"""The FCM credential, in the Windows Credential Manager and nowhere on disk.

## What this solves

Google recommends user credentials for a local workstation, and ``gcloud auth
application-default login`` writes them to
``%APPDATA%\\gcloud\\application_default_credentials.json`` as plaintext holding a
refresh token. Anyone who can read that file — another process, a backup, a
stolen laptop, a synced folder — can mint access tokens as the operator until
the grant is revoked by hand.

Workload Identity Federation is what Google prefers, and it is the wrong tool
here. WIF's no-file property comes from the workload already having a native
identity: a GKE metadata server, a GitHub Actions OIDC token, EC2 instance
metadata. A Windows laptop has none, so WIF on this machine degenerates into a
config file pointing at a token file — two files instead of one.

So the token is kept in the Windows Credential Manager, where DPAPI encrypts it
and binds it to the Windows account. The gateway reads it into memory and hands
``firebase-admin`` a dict, and the plaintext form exists only in the process heap.

## What it does not buy

Stated plainly, because the distinction is easy to gloss over:

* It does mean **no readable secret in the filesystem**. Copying the file
  elsewhere, or syncing it, yields nothing; decryption needs the same Windows
  user account on the same machine.
* It does **not** make the token short-lived. A Google refresh token lives until
  it is revoked, and the only place to revoke it is ``gcloud auth
  application-default revoke``. DPAPI protects the token at rest; it does not
  change Google's semantics.
* It does not reduce privilege. The credential still carries the operator's own
  permissions, which is Google's documented recommendation for local development
  and the reason this is preferable to a broadly-scoped service account key.

## Revoking

    gcloud auth application-default revoke
    python -m herdr_notify.cli push-credentials --delete
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import logging
import os
from pathlib import Path
from typing import Any, Final

log = logging.getLogger(__name__)

#: Where the token lives. A generic credential under a named target, rather than
#: anything inside a password manager's own namespace, so it shows up in
#: ``cmdkey /list`` and can be revoked by hand without the vendor SDK.
CREDENTIAL_TARGET: Final = "herdr-notify/fcm-refresh-token"

#: Where ``gcloud auth application-default login`` writes. Read once, at
#: migration time, only to move the token somewhere better.
ADC_PATH: Final = (
    Path(os.environ.get("APPDATA", "")) / "gcloud" / "application_default_credentials.json"
)

#: The fields ``firebase-admin`` needs. ``type`` is not optional: its
#: ``RefreshToken`` validates it and raises ``ValueError`` without it, so a
#: compacted credential that drops it parses fine here and fails later, from a
#: background thread, at send time.
REQUIRED_FIELDS: Final = ("client_id", "client_secret", "refresh_token")

CREDENTIAL_TYPE: Final = "authorized_user"


class CredentialStoreError(RuntimeError):
    """The Windows Credential Manager is unavailable or refused the operation."""


# -- Windows API -----------------------------------------------------------
# ctypes rather than the `keyring` package: this is one target and two calls, and
# a transitive dependency for that is a poor trade in a project whose argument
# partly rests on having few dependencies.

_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2
_ERROR_NOT_FOUND = 1168


class _CREDENTIAL_ATTRIBUTE(ctypes.Structure):
    _fields_ = [
        ("Keyword", ctypes.wintypes.LPWSTR),
        ("Flags", ctypes.wintypes.DWORD),
        ("ValueSize", ctypes.wintypes.DWORD),
        ("Value", ctypes.POINTER(ctypes.c_ubyte)),
    ]


class _CREDENTIAL(ctypes.Structure):
    _fields_ = [
        ("Flags", ctypes.wintypes.DWORD),
        ("Type", ctypes.wintypes.DWORD),
        ("TargetName", ctypes.wintypes.LPWSTR),
        ("Comment", ctypes.wintypes.LPWSTR),
        ("LastWritten", ctypes.wintypes.FILETIME),
        ("CredentialBlobSize", ctypes.wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", ctypes.wintypes.DWORD),
        ("AttributeCount", ctypes.wintypes.DWORD),
        ("Attributes", ctypes.POINTER(_CREDENTIAL_ATTRIBUTE)),
        ("TargetAlias", ctypes.wintypes.LPWSTR),
        ("UserName", ctypes.wintypes.LPWSTR),
    ]


def _advapi32() -> Any:
    if os.name != "nt":  # pragma: no cover - Windows-only
        raise CredentialStoreError("the Windows Credential Manager needs Windows")
    return ctypes.windll.Advapi32


def read_credential(target: str = CREDENTIAL_TARGET) -> str | None:
    """Read the stored blob, or None when nothing is stored."""
    pc_cred = ctypes.POINTER(_CREDENTIAL)()
    if not _advapi32().CredReadW(target, _CRED_TYPE_GENERIC, 0, ctypes.byref(pc_cred)):
        error = ctypes.get_last_error() or ctypes.GetLastError()
        if error == _ERROR_NOT_FOUND:
            return None
        raise CredentialStoreError(f"CredReadW failed for {target!r} (error {error})")
    try:
        cred = pc_cred.contents
        return ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize).decode("utf-8")
    finally:
        _advapi32().CredFree(pc_cred)


def write_credential(blob: str, target: str = CREDENTIAL_TARGET) -> None:
    """Store the blob, replacing anything already there."""
    data = blob.encode("utf-8")
    buffer = ctypes.create_string_buffer(data, len(data))
    cred = _CREDENTIAL()
    cred.Type = _CRED_TYPE_GENERIC
    cred.TargetName = target
    # LocalMachine persistence encrypts for this user on this machine. Enterprise
    # would roam the blob to other domain machines, which is the opposite of what
    # is wanted for a token that can send as the operator.
    cred.Persist = _CRED_PERSIST_LOCAL_MACHINE
    cred.CredentialBlobSize = len(data)
    cred.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
    cred.UserName = "herdr-notify"
    if not _advapi32().CredWriteW(ctypes.byref(cred), 0):
        error = ctypes.get_last_error() or ctypes.GetLastError()
        raise CredentialStoreError(f"CredWriteW failed for {target!r} (error {error})")


def delete_credential(target: str = CREDENTIAL_TARGET) -> bool:
    """Remove the blob. Returns whether anything was there."""
    return bool(_advapi32().CredDeleteW(target, _CRED_TYPE_GENERIC, 0))


# -- credential shaping ----------------------------------------------------


def parse_adc(raw: str) -> dict[str, Any]:
    """Pull the fields ``firebase-admin`` needs out of an ADC file or stored blob.

    Accepts both shapes — a full ``gcloud`` ADC file and the compact blob this
    module writes — rather than two functions differing by one field, because the
    two are the same operation at different moments.

    ``account`` is dropped deliberately: it is the operator's email address and
    has no business being carried around longer than it takes to build the
    credential.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CredentialStoreError(f"the credential is not valid JSON: {exc}") from exc
    declared = data.get("type")
    if declared is not None and declared != CREDENTIAL_TYPE:
        raise CredentialStoreError(
            f"expected a {CREDENTIAL_TYPE!r} credential, got {declared!r}. "
            "A service account key is a different setup."
        )
    missing = [f for f in REQUIRED_FIELDS if not data.get(f)]
    if missing:
        raise CredentialStoreError(f"the credential is missing {', '.join(missing)}")
    return {**{f: str(data[f]) for f in REQUIRED_FIELDS}, "type": CREDENTIAL_TYPE}


def migrate_from_adc(path: Path | None = None, *, delete_source: bool = True) -> dict[str, Any]:
    """Move the ADC refresh token into the Credential Manager.

    The source is removed by default. Leaving a plaintext copy behind after
    claiming to have secured it would be the worst of both, and the file is
    re-creatable with one command if it is ever needed again.
    """
    source = path or ADC_PATH
    if not source.is_file():
        raise CredentialStoreError(f"no ADC file at {source}")
    credential = parse_adc(source.read_text(encoding="utf-8"))
    write_credential(json.dumps(credential))
    if delete_source:
        source.unlink()
        log.info("removed the plaintext ADC file at %s", source)
    return credential


def load_refresh_token(target: str = CREDENTIAL_TARGET) -> dict[str, Any] | None:
    """Read and validate the stored token. None when nothing is stored."""
    raw = read_credential(target)
    return None if raw is None else parse_adc(raw)


__all__ = [
    "ADC_PATH",
    "CREDENTIAL_TARGET",
    "CREDENTIAL_TYPE",
    "CredentialStoreError",
    "delete_credential",
    "load_refresh_token",
    "migrate_from_adc",
    "parse_adc",
    "read_credential",
    "write_credential",
]
