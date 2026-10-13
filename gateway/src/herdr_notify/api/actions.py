"""Typed actions: the only way a phone can affect an agent.

The gateway holds a socket that can start agents, submit prompts, and write raw
keystrokes into any pane. If the API let a client name a herdr method and pass
its parameters through, then anything that could reach the endpoint would have
the full surface — arbitrary prompts to a running coding agent, arbitrary
keystrokes, arbitrary text into any pane on the machine.

So the client names an *action*, never a method. Each action maps to exactly one
herdr call with a fixed parameter shape, and the variable parts are constrained:

* **Keys are allowlisted.** Not "any string herdr happens to accept" — an
  explicit set of navigation and answer keys. A passthrough would let a caller
  send ``ctrl+c`` to any pane at will, or type into a pane nobody was watching.
* **Ctrl-C is guarded.** It interrupts whatever an agent is doing, so the caller
  must also send ``confirm: true``. The app renders that as a confirmation
  dialog, which is the honest representation of what the button does.
* **Targets are resolved to a known pane.** herdr accepts a live agent name or a
  pane id, and resolves either. Restricting the target to a pane id the gateway
  already mirrors removes the possibility of addressing an agent that has since
  been renamed or replaced.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

#: Keys a caller may send without further ceremony: navigation, and the answers
#: to the yes/no and numbered dialogs agents actually present.
SAFE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "up",
        "down",
        "left",
        "right",
        "enter",
        "esc",
        "escape",
        "tab",
        "space",
        "backspace",
        "home",
        "end",
        "pgup",
        "pgdown",
        "y",
        "n",
        *tuple(str(d) for d in range(10)),
    }
)

#: Keys that change or destroy work, and therefore need explicit confirmation.
GUARDED_KEYS: Final[frozenset[str]] = frozenset({"ctrl+c"})

#: Anything outside both sets is refused. herdr validates keys too, but its
#: vocabulary is every key it can decode, which is far wider than what a phone
#: has any business sending.
ALLOWED_KEYS: Final = SAFE_KEYS | GUARDED_KEYS

#: Cap on a pane read. The app renders a snippet, not a terminal buffer.
MAX_READ_LINES: Final = 200
DEFAULT_READ_LINES: Final = 60

#: The pane source a read asks for by default: the soft-wrapped history a person
#: actually saw. herdr refuses it while the pane is on its alternate screen
#: (a working full-screen agent), so the route falls back to
#: :data:`READ_FALLBACK_SOURCE` rather than failing the read.
READ_SOURCE: Final = "recent_unwrapped"
#: What a read falls back to when herdr refuses the history source. The visible
#: screen is always capturable, whatever the pane's state.
READ_FALLBACK_SOURCE: Final = "visible"

#: Pane ids look like ``w1:p3``. Anything else is not a pane the gateway
#: mirrors, and passing an arbitrary string through to herdr's target
#: resolution would let a caller address agents by name instead.
PANE_ID_RE: Final = re.compile(r"^[A-Za-z0-9]{1,32}:p[0-9A-Za-z]{1,32}$")


class ActionError(Exception):
    """An action was refused. ``code`` is safe to return to the caller."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ActionKind(StrEnum):
    RESPOND = "respond"
    SEND_KEYS = "keys"
    FOCUS = "focus"
    READ = "read"


def validate_pane_id(pane_id: str) -> str:
    """Accept only a pane id, never a bare agent name."""
    if not PANE_ID_RE.match(pane_id or ""):
        raise ActionError("bad_pane", f"{pane_id!r} is not a pane id")
    return pane_id


def validate_keys(keys: list[str], *, confirm: bool = False) -> list[str]:
    """Normalise and allowlist the keys a caller wants to send."""
    if not keys:
        raise ActionError("no_keys", "at least one key is required")
    if len(keys) > 8:
        raise ActionError("too_many_keys", "at most 8 keys per request")
    normalised: list[str] = []
    for key in keys:
        candidate = (key or "").strip().lower()
        if not candidate:
            raise ActionError("empty_key", "keys must not be empty")
        if candidate in GUARDED_KEYS and not confirm:
            # Naming the required confirmation in the error keeps the app's
            # behaviour obvious without documenting it twice.
            raise ActionError(
                "confirmation_required",
                f"{candidate} changes running work and requires confirm=true",
            )
        if candidate not in ALLOWED_KEYS:
            raise ActionError("key_not_allowed", f"{candidate!r} is not an allowed key")
        if candidate == "escape":
            candidate = "esc"
        normalised.append(candidate)
    return normalised


def validate_prompt(text: str) -> str:
    """Content-check a submitted prompt."""
    cleaned = (text or "").strip()
    if not cleaned:
        raise ActionError("empty_prompt", "text is required")
    # A control character here would be typed into the agent's TTY as something
    # other than text. Newlines are legitimate (multi-line instructions), so
    # only the characters that actually break a terminal line are refused.
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", cleaned):
        raise ActionError("control_characters", "prompt contains control characters")
    return cleaned


def clamp_read_lines(lines: int | None) -> int:
    if lines is None:
        return DEFAULT_READ_LINES
    if lines < 1:
        return 1
    return min(lines, MAX_READ_LINES)


@dataclass(frozen=True, slots=True)
class AgentAction:
    """A validated request, expressed in herdr's own parameter shape."""

    kind: ActionKind
    target: str
    params: dict[str, object]

    def method_params(self) -> tuple[str, dict[str, object]]:
        """Return the (method, params) pair to send over the socket."""
        match self.kind:
            case ActionKind.RESPOND:
                return "agent.prompt", dict(self.params)
            case ActionKind.SEND_KEYS:
                return "agent.send_keys", dict(self.params)
            case ActionKind.FOCUS:
                return "agent.focus", {"target": self.target}
            case ActionKind.READ:
                return "agent.read", dict(self.params)


def build_respond(pane_id: str, text: str) -> AgentAction:
    return AgentAction(
        kind=ActionKind.RESPOND,
        target=validate_pane_id(pane_id),
        params={"target": validate_pane_id(pane_id), "text": validate_prompt(text)},
    )


def build_send_keys(pane_id: str, keys: list[str], *, confirm: bool = False) -> AgentAction:
    target = validate_pane_id(pane_id)
    return AgentAction(
        kind=ActionKind.SEND_KEYS,
        target=target,
        params={"target": target, "keys": validate_keys(keys, confirm=confirm)},
    )


def build_focus(pane_id: str) -> AgentAction:
    target = validate_pane_id(pane_id)
    return AgentAction(kind=ActionKind.FOCUS, target=target, params={"target": target})


def build_read(
    pane_id: str,
    lines: int | None = None,
    *,
    source: str = READ_SOURCE,
) -> AgentAction:
    target = validate_pane_id(pane_id)
    return AgentAction(
        kind=ActionKind.READ,
        target=target,
        params={
            "target": target,
            # snake_case here; the CLI's recent-unwrapped is a different spelling
            # of the same value and herdr rejects it on the raw socket.
            "source": source,
            "lines": clamp_read_lines(lines),
        },
    )


__all__ = [
    "ALLOWED_KEYS",
    "DEFAULT_READ_LINES",
    "GUARDED_KEYS",
    "MAX_READ_LINES",
    "PANE_ID_RE",
    "READ_FALLBACK_SOURCE",
    "READ_SOURCE",
    "SAFE_KEYS",
    "ActionError",
    "ActionKind",
    "AgentAction",
    "build_focus",
    "build_read",
    "build_respond",
    "build_send_keys",
    "clamp_read_lines",
    "validate_keys",
    "validate_pane_id",
    "validate_prompt",
]
