"""Per-device authorization: which endpoint a device may call.

Authentication answers who you are; this answers what you may do. A valid
signature never implies authorization: the grant is an explicit list on the
device's trust-store record, checked against the endpoint matrix below.

The matrix is load-bearing. An endpoint added without a rule here fails closed
— a 403, not an implicit allowance — so a new endpoint cannot start life
authorized by accident. That is the failure mode M2 exists to close: before
this module, every authenticated device could drive every action, and the
gateway can submit prompts and write keystrokes into real coding agents.

Failures are reported as a reason string and never distinguish "no such
permission" from "no such endpoint" to the caller, the same oracle reasoning as
the uniform 401. The distinction is kept for the server log, which is the audit
trail.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Final

from .devices import Device, Permission

#: The agent action endpoints, by their last path segment. The pane id between
#: them is not validated here — actions.py owns that — because the matrix
#: classifies the endpoint, not the target: a malformed pane id is an action
#: error (400), never an authorization one.
_ACTION_PATH_RE: Final = re.compile(r"^/v1/agents/[^/]+/(respond|keys|focus|seen|read|image)$")

#: Device management: ``POST /v1/devices/{device_id}/revoke``. The id is a
#: single path segment and is not validated here (the handler answers 404 for an
#: unknown id): the matrix classifies the endpoint, not the target.
_DEVICE_REVOKE_RE: Final = re.compile(r"^/v1/devices/[^/]+/revoke$")

#: The permission each agent action requires. ``focus`` sits behind RESPOND
#: because it drives herdr (``agent.focus``): a device granted only READ_STATE
#: observes but never drives. ``seen`` and ``read`` sit behind READ_STATE:
#: marking an agent seen is non-destructive and reversible, and ``read``
#: mutates nothing — the write-budget rate limit already prices the herdr
#: round trip each costs. RESPOND stays for approving, denying and sending.
_ACTION_PERMISSION: Final = {
    "respond": Permission.RESPOND,
    "keys": Permission.SEND_KEY,
    "focus": Permission.RESPOND,
    "seen": Permission.READ_STATE,
    "read": Permission.READ_STATE,
    "image": Permission.RESPOND,
}


class AuthzRejection(StrEnum):
    """Why an authorized request was refused. Never sent verbatim to the caller."""

    NOT_PERMITTED = "not_permitted"
    UNKNOWN_ENDPOINT = "unknown_endpoint"


class AuthorizationError(Exception):
    """An authenticated request was refused by authorization."""

    def __init__(
        self, rejection: AuthzRejection, *, required: Permission | None = None
    ) -> None:
        super().__init__(rejection)
        self.rejection = rejection
        self.required = required

    @property
    def public_message(self) -> str:
        """What the caller is told. Deliberately non-specific.

        Naming which permission or endpoint failed has no legitimate client:
        the fix is a host-side grant, never a client-side retry. The reason,
        the device id and the required permission go to the server log.
        """
        return "forbidden"


def required_permission(method: str, target: str) -> Permission | None:
    """The permission an endpoint requires, or ``None`` when it needs none.

    ``target`` is the raw request target exactly as signed; the query string is
    not part of the match. Raises :class:`UnknownEndpoint` when no rule
    matches, so an endpoint without a matrix entry fails closed rather than
    open.
    """
    path = target.partition("?")[0]
    verb = method.upper()
    if verb == "GET" and path == "/v1/health":
        # Public by design (api.md). Listed so the matrix is auditable in one
        # place; the endpoint carries no auth dependency at all.
        return None
    if verb == "GET" and path == "/v1/state":
        return Permission.READ_STATE
    if verb == "GET" and path == "/v1/events":
        return Permission.READ_STATE
    if verb == "GET" and path == "/v1/peers":
        # The tailnet's machine names and addresses: read-only, like the state.
        return Permission.READ_STATE
    if verb == "GET" and path == "/v1/devices":
        # "My devices": device management. ADMIN was RESERVED in M2 with no
        # endpoint; Fase 2(c) activates it for exactly this surface.
        return Permission.ADMIN
    if verb == "POST" and _DEVICE_REVOKE_RE.match(path):
        # Revoking a device is destructive, so it stays behind ADMIN rather than
        # READ_STATE: a read-only phone observes, it does not withdraw access.
        return Permission.ADMIN
    if verb == "POST" and path == "/v1/pair":
        # Unauthenticated by design: the pairing code (or the tailnet owner
        # check) is the authorisation, and the endpoint never runs through
        # `require_device`. Listed so the matrix stays auditable in one place,
        # like /v1/health.
        return None
    if verb == "POST" and path == "/v1/me/fcm-token":
        # Self-service on the caller's own record: the device id comes from the
        # signature, never the body, so no device can touch another's token.
        return None
    if verb == "POST" and path == "/v1/workspaces":
        # Starting a new conversation launches an agent on the host.
        return Permission.RESPOND
    if verb == "POST":
        action = _ACTION_PATH_RE.match(path)
        if action is not None:
            return _ACTION_PERMISSION[action.group(1)]
    raise UnknownEndpoint(f"no authorization rule for {verb} {path}")


def authorize(device: Device, *, method: str, target: str) -> None:
    """Authorization, or raise :class:`AuthorizationError`.

    Runs after authentication succeeds and before the rate limit, so an
    unauthorized request consumes no rate budget and leaves no last-seen
    trace — the same way a revoked device never reaches either.
    """
    try:
        required = required_permission(method, target)
    except UnknownEndpoint as exc:
        raise AuthorizationError(AuthzRejection.UNKNOWN_ENDPOINT) from exc
    if required is None:
        return
    if required not in device.permissions:
        raise AuthorizationError(AuthzRejection.NOT_PERMITTED, required=required)


class UnknownEndpoint(Exception):
    """No matrix rule matches this method and path. Fail closed."""


__all__ = [
    "AuthorizationError",
    "AuthzRejection",
    "UnknownEndpoint",
    "authorize",
    "required_permission",
]
