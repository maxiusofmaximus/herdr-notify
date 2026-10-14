"""The control plane's HTTP surface, and the refusals it must make.

Two things are under test. First, that a correctly signed request works end to
end against a fake herdr. Second, and more importantly, that the ways to abuse
this endpoint are all closed: unsigned access, method passthrough, arbitrary
keystrokes, unbounded prompts, and replay.

The abuse tests matter more than the happy path. A control plane that can send
prompts and keystrokes to real coding agents is the highest-value target in the
project, and a missing allowlist is not a bug that shows up in a demo.
"""

from __future__ import annotations

import base64
import json
import secrets
import time
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from herdr_notify.api.actions import (
    READ_FALLBACK_SOURCE,
    READ_SOURCE,
    ActionError,
    build_read,
    build_respond,
    build_send_keys,
    validate_keys,
    validate_pane_id,
    validate_prompt,
)
from herdr_notify.api.app import (
    MAX_SIGNED_BODY,
    ApiConfig,
    AppContext,
    _signed_body_limit,
    create_app,
    opening_state_frame,
    state_payload,
)
from herdr_notify.api.auth import (
    CURVE_P256,
    HEADER_DEVICE,
    HEADER_NONCE,
    HEADER_SIGNATURE,
    HEADER_TIMESTAMP,
    PERMISSION_READ_STATE,
    PERMISSION_RESPOND,
    PERMISSION_SEND_KEY,
    DeviceStore,
    RequestVerifier,
    build_signing_string,
)
from herdr_notify.api.images import MAX_IMAGE_BODY_BYTES, image_prompt
from herdr_notify.api.ratelimit import RateLimiter, StreamRegistry
from herdr_notify.herdr.client import HerdrError
from herdr_notify.state.models import Snapshot
from herdr_notify.state.store import Store
from tests.fake_herdr import FakeHerdr, agent_record, workspace_record

# -- unit: the allowlists --------------------------------------------------


@pytest.mark.parametrize("pane_id", ["w1:p1", "wA:p9", "abc:px"])
def test_valid_pane_ids_are_accepted(pane_id: str) -> None:
    assert validate_pane_id(pane_id) == pane_id


@pytest.mark.parametrize(
    "pane_id",
    [
        "reviewer",  # a bare agent name: herdr would resolve it, we must not
        "",
        "../../etc/passwd",
        "w1:p1 extra",
        "w1",
        "w1:p1\nx",
    ],
)
def test_non_pane_targets_are_refused(pane_id: str) -> None:
    with pytest.raises(ActionError) as excinfo:
        validate_pane_id(pane_id)
    assert excinfo.value.code == "bad_pane"


@pytest.mark.parametrize("key", ["up", "down", "enter", "esc", "tab", "y", "n", "1", "9"])
def test_dialog_keys_are_allowed(key: str) -> None:
    assert validate_keys([key]) == [key]


def test_ctrl_c_requires_confirmation() -> None:
    with pytest.raises(ActionError) as excinfo:
        validate_keys(["ctrl+c"])
    assert excinfo.value.code == "confirmation_required"
    assert validate_keys(["ctrl+c"], confirm=True) == ["ctrl+c"]


@pytest.mark.parametrize("key", ["ctrl+z", "ctrl+s", "a", "Z", "f1", "meta+x", "'", " ' "])
def test_other_keys_are_refused(key: str) -> None:
    """A passthrough would let a caller type into any pane on the machine."""
    with pytest.raises(ActionError):
        validate_keys([key])


def test_keys_are_normalised() -> None:
    assert validate_keys(["ESC", " Enter "]) == ["esc", "enter"]
    assert validate_keys(["escape"]) == ["esc"]


def test_too_many_keys_are_refused() -> None:
    with pytest.raises(ActionError) as excinfo:
        validate_keys(["up"] * 9)
    assert excinfo.value.code == "too_many_keys"


def test_a_prompt_has_no_length_cap() -> None:
    assert validate_prompt("sí, hazlo") == "sí, hazlo"
    long_message = "x" * 5000
    assert validate_prompt(long_message) == long_message


def test_empty_prompt_is_refused() -> None:
    with pytest.raises(ActionError):
        validate_prompt("   ")


def test_prompt_may_contain_newlines_but_not_control_characters() -> None:
    assert validate_prompt("line one\nline two") == "line one\nline two"
    with pytest.raises(ActionError) as excinfo:
        validate_prompt("hello\x00world")
    assert excinfo.value.code == "control_characters"


def test_actions_map_to_exactly_one_herdr_method() -> None:
    assert build_respond("w1:p1", "sí").method_params()[0] == "agent.prompt"
    assert build_send_keys("w1:p1", ["enter"]).method_params()[0] == "agent.send_keys"
    assert build_read("w1:p1", 20).method_params()[1]["source"] == "recent_unwrapped"


def test_read_lines_are_clamped() -> None:
    assert build_read("w1:p1", 10_000).params["lines"] == 200
    assert build_read("w1:p1", 0).params["lines"] == 1
    assert build_read("w1:p1", None).params["lines"] == 60


# -- rate limiting ---------------------------------------------------------


def test_writes_are_limited_per_device() -> None:
    class Clock:
        def __init__(self) -> None:
            self.now = 1000.0

        def __call__(self) -> float:
            return self.now

    clock = Clock()
    limiter = RateLimiter(read_per_minute=100, write_per_minute=3, clock=clock)
    for _ in range(3):
        assert limiter.allow("dev-1", write=True)[0] is True
    allowed, retry_after = limiter.allow("dev-1", write=True)
    assert allowed is False
    assert retry_after > 0
    clock.now += 61
    assert limiter.allow("dev-1", write=True)[0] is True


def test_limits_are_per_device() -> None:
    limiter = RateLimiter(read_per_minute=1, write_per_minute=1, clock=lambda: 1000.0)
    assert limiter.allow("dev-1", write=True)[0] is True
    assert limiter.allow("dev-1", write=True)[0] is False
    assert limiter.allow("dev-2", write=True)[0] is True


def test_stream_count_is_capped_per_device() -> None:
    registry = StreamRegistry(per_device=2)
    assert registry.acquire("dev-1") is True
    assert registry.acquire("dev-1") is True
    assert registry.acquire("dev-1") is False
    assert registry.acquire("dev-2") is True
    registry.release("dev-1")
    assert registry.acquire("dev-1") is True


# -- end to end ------------------------------------------------------------


class FakeClient:
    """A HerdrClient-shaped adapter over the fake, using the real protocol."""

    def __init__(self, fake: FakeHerdr) -> None:
        self._fake = fake
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append((method, params or {}))
        answer = {
            "agent.prompt": {
                "type": "agent_prompt",
                "agent": {
                    "pane_id": (params or {}).get("target"),
                    "agent": "opencode",
                    "agent_status": "idle",
                },
            },
            "agent.send_keys": {"type": "agent_keys_sent"},
            "agent.focus": {"type": "agent_focused"},
            "agent.read": {
                "type": "agent_read",
                "read": {"pane_id": (params or {}).get("target"), "text": "output"},
            },
        }.get(method)
        if answer is not None:
            return answer
        return self._fake.request_over_socket(method, params or {})

    @property
    def last_call(self) -> tuple[str, dict[str, Any]] | None:
        return self.calls[-1] if self.calls else None


class NewPhone:
    """A keypair that can sign, used to simulate a second handset."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.key = ec.generate_private_key(ec.SECP256R1())

    def public_bytes(self) -> bytes:
        return self.key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )

    def signed(
        self, method: str, path: str, body: bytes = b"", device_id: str = ""
    ) -> dict[str, str]:
        device = device_id or f"dev-{self.label}"
        moment = int(time.time())
        nonce = base64.b64encode(secrets.token_bytes(16)).decode()
        message = build_signing_string(
            method=method, target=path, body=body, timestamp=moment, nonce=nonce
        )
        return {
            HEADER_DEVICE: device,
            HEADER_TIMESTAMP: str(moment),
            HEADER_NONCE: nonce,
            HEADER_SIGNATURE: base64.b64encode(
                self.key.sign(message, ec.ECDSA(hashes.SHA256()))
            ).decode(),
        }


class Harness:
    """A running app wired to a fake herdr, plus one enrolled signing key."""

    def __init__(self, tmp_path: Any) -> None:
        self.fake = FakeHerdr()
        self.fake.set_snapshot(
            agents=[
                agent_record("w1:p1", "w1", status="blocked"),
                agent_record("w2:p1", "w2", status="working"),
            ],
            workspaces=[workspace_record("w1", "alpha"), workspace_record("w2", "beta")],
        )
        self.store = Store()
        self.store.install(Snapshot.model_validate(self.fake.snapshot_payload))

        self.devices = DeviceStore(tmp_path / "devices.json")
        self.key = ec.generate_private_key(ec.SECP256R1())
        public = self.key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        code = self.devices.issue_enrollment_code().code
        self.device = self.devices.enroll(
            code=code,
            curve=CURVE_P256,
            public_key=base64.b64encode(public).decode(),
            label="pixel",
            # The action tests below exercise action validation, not
            # authorization, so this device carries the act grants explicitly.
            # The authorization behaviour has its own device — the restricted
            # phone below, which holds only the pairing default.
            permissions=[PERMISSION_READ_STATE, PERMISSION_RESPOND, PERMISSION_SEND_KEY],
        )

        # A default-paired device: READ_STATE only. The 403 tests use it,
        # because a newly paired device may observe and nothing more.
        self.restricted_key = ec.generate_private_key(ec.SECP256R1())
        restricted_public = self.restricted_key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        code = self.devices.issue_enrollment_code().code
        self.restricted = self.devices.enroll(
            code=code,
            curve=CURVE_P256,
            public_key=base64.b64encode(restricted_public).decode(),
            label="watch-only",
        )

        self.herdr = FakeClient(self.fake)
        self.context = AppContext(
            store=self.store,
            devices=self.devices,
            verifier=RequestVerifier(self.devices),
            limiter=RateLimiter(read_per_minute=1000, write_per_minute=1000),
            streams=StreamRegistry(per_device=4),
            client=self.herdr,  # type: ignore[arg-type]
            subscribers=set(),
        )
        self.images = tmp_path / "images"
        self.app = create_app(
            self.context,
            ApiConfig(
                device_store_path=tmp_path / "d.json",
                image_store_dir=self.images,
            ),
        )
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def close(self) -> None:
        self.fake.close()

    def sign(
        self, method: str, path: str, body: bytes = b"", nonce: str | None = None
    ) -> dict[str, str]:
        moment = int(time.time())
        unique = nonce or base64.b64encode(secrets.token_bytes(16)).decode()
        message = build_signing_string(
            method=method,
            target=path,
            body=body,
            timestamp=moment,
            nonce=unique,
            max_body=MAX_IMAGE_BODY_BYTES,
        )
        signature = self.key.sign(message, ec.ECDSA(hashes.SHA256()))
        return {
            HEADER_DEVICE: self.device.device_id,
            HEADER_TIMESTAMP: str(moment),
            HEADER_NONCE: unique,
            HEADER_SIGNATURE: base64.b64encode(signature).decode(),
        }

    def call(self, method: str, path: str, payload: Any = None) -> Any:
        body = b"" if payload is None else json.dumps(payload).encode()
        headers = self.sign(method, path, body)
        return self.client.request(method, path, content=body, headers=headers)

    def call_as(
        self, device: Any, key: Any, method: str, path: str, payload: Any = None
    ) -> Any:
        """A signed request from a specific device, for the authorization tests."""
        body = b"" if payload is None else json.dumps(payload).encode()
        headers = self.sign_for(device, key, method, path, body)
        return self.client.request(method, path, content=body, headers=headers)

    def sign_for(
        self, device: Any, key: Any, method: str, path: str, body: bytes = b""
    ) -> dict[str, str]:
        moment = int(time.time())
        nonce = base64.b64encode(secrets.token_bytes(16)).decode()
        message = build_signing_string(
            method=method,
            target=path,
            body=body,
            timestamp=moment,
            nonce=nonce,
            max_body=MAX_IMAGE_BODY_BYTES,
        )
        return {
            HEADER_DEVICE: device.device_id,
            HEADER_TIMESTAMP: str(moment),
            HEADER_NONCE: nonce,
            HEADER_SIGNATURE: base64.b64encode(
                key.sign(message, ec.ECDSA(hashes.SHA256()))
            ).decode(),
        }


@pytest.fixture
def app_client(tmp_path: Any) -> Any:
    harness = Harness(tmp_path)
    try:
        yield harness
    finally:
        harness.close()


def test_health_is_open_but_says_nothing_useful(app_client: Harness) -> None:
    """An unauthenticated endpoint must not describe the operator's machine."""
    response = app_client.client.get("/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert "agents" not in body
    assert "herdr_version" not in body
    assert "workspaces" not in body


def test_state_requires_a_signature(app_client: Harness) -> None:
    assert app_client.client.get("/v1/state").status_code == 401


def test_a_signed_read_returns_ranked_agents(app_client: Harness) -> None:
    response = app_client.call("GET", "/v1/state")
    assert response.status_code == 200
    body = response.json()
    assert [a["status"] for a in body["agents"]] == ["blocked", "working"]
    assert body["agents"][0]["project"] == "alpha"
    assert body["counts"] == {"blocked": 1, "working": 1}


def test_the_sse_opening_frame_is_the_same_state_model(app_client: Harness) -> None:
    """The stream and the poll must not disagree about the same session.

    The opening frame used to carry the raw reduced view, whose agent entries
    have no ``attention`` and whose ``counts`` tallies collections rather than
    statuses, while ``/v1/state`` carried ranked triage rows. A phone joining the
    stream therefore ranked from a payload the gateway never ranked, and the two
    endpoints could describe one session differently.
    """
    # The exact frame the stream sends first, without driving a never-ending
    # stream through the test client.
    frame = json.loads(opening_state_frame(app_client.context))
    state = frame["state"]

    # The ranked shape /v1/state serves, not the raw reduced view: a status
    # tally rather than collection sizes, and agents carrying their attention.
    assert state["counts"] == {"blocked": 1, "working": 1}
    assert [a["status"] for a in state["agents"]] == ["blocked", "working"]
    assert state["agents"][0]["attention"] == 3
    assert state["revision"] == app_client.store.state.revision
    # And byte-identical to the read model: one state, two transports.
    assert state == state_payload(app_client.context)


def test_an_unsigned_action_is_refused(app_client: Harness) -> None:
    response = app_client.client.post("/v1/agents/w1:p1/respond", json={"text": "sí"})
    assert response.status_code == 401


def test_respond_reaches_herdr(app_client: Harness) -> None:
    response = app_client.call("POST", "/v1/agents/w1:p1/respond", {"text": "sí, hazlo"})
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_a_chat_message_has_no_length_cap(app_client: Harness) -> None:
    """A prompt longer than the old 4000-character cap still reaches herdr."""
    message = "x" * 9000
    response = app_client.call("POST", "/v1/agents/w1:p1/respond", {"text": message})
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_keys_reach_herdr_when_allowed(app_client: Harness) -> None:
    response = app_client.call("POST", "/v1/agents/w1:p1/keys", {"keys": ["enter"]})
    assert response.status_code == 200


def test_ctrl_c_over_http_is_refused_without_confirmation(app_client: Harness) -> None:
    response = app_client.call("POST", "/v1/agents/w1:p1/keys", {"keys": ["ctrl+c"]})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "confirmation_required"


def test_ctrl_c_over_http_is_allowed_with_confirmation(app_client: Harness) -> None:
    response = app_client.call(
        "POST", "/v1/agents/w1:p1/keys", {"keys": ["ctrl+c"], "confirm": True}
    )
    assert response.status_code == 200


def test_an_allowlisted_key_list_cannot_smuggle_another(app_client: Harness) -> None:
    response = app_client.call("POST", "/v1/agents/w1:p1/keys", {"keys": ["enter", "ctrl+z"]})
    assert response.status_code == 400


def test_a_bare_agent_name_is_refused(app_client: Harness) -> None:
    response = app_client.call("POST", "/v1/agents/reviewer/respond", {"text": "sí"})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "bad_pane"


def test_mark_seen_does_not_move_herdr_focus(app_client: Harness) -> None:
    """Opening a chat must not move the operator's focus in the terminal.

    herdr 0.9.1 only clears a "done" badge via ``agent.focus``, which also moves
    the terminal's focus to that pane. The phone marks the agent seen in the app
    instead, so this route must not reach herdr at all.
    """
    app_client.herdr.calls.clear()
    response = app_client.call("POST", "/v1/agents/w1:p1/seen")
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert app_client.herdr.calls == [], "seen must not call herdr"


def test_mark_seen_still_refuses_a_bare_agent_name(app_client: Harness) -> None:
    response = app_client.call("POST", "/v1/agents/reviewer/seen")
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "bad_pane"


def test_read_returns_text(app_client: Harness) -> None:
    response = app_client.call("POST", "/v1/agents/w1:p1/read", {"lines": 20})
    assert response.status_code == 200
    assert response.json()["text"] == "output"


def test_read_falls_back_to_visible_when_herdr_refuses_the_history_source(
    app_client: Harness,
) -> None:
    """Reading while the agent works must not surface herdr's 409.

    herdr refuses the history source (``recent_unwrapped``/``recent``) while the
    pane is on its alternate screen — "cannot read 60 lines while w1:p1 is
    working ... use --source visible" — which is exactly when the phone wants to
    look. Answering the 409 would make every read of a working agent fail, so the
    route retries with the visible screen.
    """
    seen_sources: list[str] = []

    class RefusingHistory:
        async def request(
            self, method: str, params: dict[str, Any] | None = None
        ) -> dict[str, Any]:
            params = params or {}
            seen_sources.append(str(params.get("source")))
            if params.get("source") != READ_FALLBACK_SOURCE:
                raise HerdrError("agent.read: cannot read while working")
            return {
                "type": "pane_read",
                "read": {"pane_id": params.get("target"), "text": "screen"},
            }

    app_client.context.client = RefusingHistory()  # type: ignore[assignment]
    response = app_client.call("POST", "/v1/agents/w1:p1/read", {"lines": 20})
    assert response.status_code == 200
    assert response.json()["text"] == "screen"
    assert seen_sources == [READ_SOURCE, READ_FALLBACK_SOURCE]


def test_read_still_answers_409_when_the_visible_screen_is_refused_too(
    app_client: Harness,
) -> None:
    """A working pane that refuses both sources is a conflict, not a gone one.

    The fallback turns herdr's alternate-screen refusal into a 200; if herdr
    refuses the visible screen as well, the 409 still has to reach the phone,
    which renders it as "the agent is working" rather than a fault.
    """
    seen_sources: list[str] = []

    class RefusingEverything:
        async def request(
            self, method: str, params: dict[str, Any] | None = None
        ) -> dict[str, Any]:
            params = params or {}
            seen_sources.append(str(params.get("source")))
            raise HerdrError("agent.read: cannot read while working")

    app_client.context.client = RefusingEverything()  # type: ignore[assignment]
    response = app_client.call("POST", "/v1/agents/w1:p1/read", {"lines": 20})
    assert response.status_code == 409
    assert seen_sources == [READ_SOURCE, READ_FALLBACK_SOURCE]


# -- a pane that no longer exists -------------------------------------------


class GoneHerdr:
    """herdr's answer for the pane of an agent the operator closed.

    The one refusal that is a state of the world rather than a mood: no
    retry, no fallback, and a code the phone can branch on.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = params or {}
        self.calls.append((method, payload))
        raise HerdrError(
            f"{method}: agent target {payload.get('target')} not found",
            code="agent_not_found",
        )


def test_a_read_of_a_gone_pane_is_a_404_with_a_stable_code(app_client: Harness) -> None:
    """The chat left open for a closed pane must not render as a read failure.

    Before, herdr's ``agent_not_found`` was mapped to the generic 409 and the
    phone showed its red "No se pudo leer la salida del agente" while retrying
    forever. The visible-screen fallback must not run either: herdr has
    already said the pane is not there to read.
    """
    gone = GoneHerdr()
    app_client.context.client = gone  # type: ignore[assignment]
    response = app_client.call("POST", "/v1/agents/wQ:pG/read", {"lines": 20})
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["code"] == "agent_not_found"
    assert "wQ:pG" in detail["message"]
    assert [method for method, _ in gone.calls] == ["agent.read"], "no fallback retry"


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/v1/agents/wQ:pG/respond", {"text": "sí"}),
        ("/v1/agents/wQ:pG/keys", {"keys": ["enter"]}),
        ("/v1/agents/wQ:pG/focus", None),
    ],
)
def test_the_act_routes_answer_404_for_a_gone_pane(
    app_client: Harness, path: str, payload: dict[str, Any] | None
) -> None:
    app_client.context.client = GoneHerdr()  # type: ignore[assignment]
    response = app_client.call("POST", path, payload)
    assert response.status_code == 404, path
    assert response.json()["detail"]["code"] == "agent_not_found", path


def test_seen_for_a_pane_the_gateway_does_not_mirror_is_404(app_client: Harness) -> None:
    """"seen" never reaches herdr, so its answer comes from the mirror.

    A phone acknowledging a badge for an agent that is already gone gets the
    same 404 and the same code as every other route, from the one source that
    can answer it without a herdr round trip.
    """
    app_client.herdr.calls.clear()
    response = app_client.call("POST", "/v1/agents/wQ:pG/seen")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "agent_not_found"
    assert app_client.herdr.calls == [], "seen must not call herdr"


# -- image attachments ------------------------------------------------------

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"fake png body"
JPEG_BYTES = b"\xff\xd8\xff" + b"fake jpeg body"
WEBP_BYTES = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"fake webp body"


def image_payload(data: bytes, mime: str) -> dict[str, str]:
    return {"mime": mime, "data": base64.b64encode(data).decode()}


def test_the_image_route_gets_its_own_body_cap() -> None:
    """An encoded picture does not fit the 256 KiB every other body is held to."""
    assert _signed_body_limit("/v1/agents/w1:p1/image") == MAX_IMAGE_BODY_BYTES
    assert _signed_body_limit("/v1/agents/w1:p1/respond") == MAX_SIGNED_BODY
    assert MAX_IMAGE_BODY_BYTES > MAX_SIGNED_BODY


def test_image_requires_a_signature(app_client: Harness) -> None:
    response = app_client.client.post(
        "/v1/agents/w1:p1/image", json=image_payload(PNG_BYTES, "image/png")
    )
    assert response.status_code == 401


@pytest.mark.parametrize(
    ("data", "mime"),
    [(PNG_BYTES, "image/png"), (JPEG_BYTES, "image/jpeg"), (WEBP_BYTES, "image/webp")],
)
def test_an_image_is_stored_and_its_path_is_prompted(
    app_client: Harness, data: bytes, mime: str
) -> None:
    response = app_client.call("POST", "/v1/agents/w1:p1/image", image_payload(data, mime))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["pane_id"] == "w1:p1"

    stored = Path(body["path"])
    assert stored.is_file(), "the gateway should have written the image"
    assert stored.parent == app_client.images.resolve()
    assert stored.read_bytes() == data

    prompts = [params for method, params in app_client.herdr.calls if method == "agent.prompt"]
    assert prompts, "the agent should have been told where the image is"
    assert prompts[-1]["text"] == image_prompt(stored)


def test_an_image_larger_than_the_small_signed_cap_is_accepted(app_client: Harness) -> None:
    """The per-route cap is what makes a multi-hundred-KB image possible."""
    big = b"\x89PNG\r\n\x1a\n" + b"a" * 400_000
    response = app_client.call("POST", "/v1/agents/w1:p1/image", image_payload(big, "image/png"))
    assert response.status_code == 200
    assert Path(response.json()["path"]).read_bytes() == big


def test_a_read_only_device_cannot_send_an_image(app_client: Harness) -> None:
    response = app_client.call_as(
        app_client.restricted,
        app_client.restricted_key,
        "POST",
        "/v1/agents/w1:p1/image",
        image_payload(PNG_BYTES, "image/png"),
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "forbidden"}


@pytest.mark.parametrize("mime", ["image/gif", "image/heic", "application/octet-stream"])
def test_a_disallowed_image_type_is_refused(app_client: Harness, mime: str) -> None:
    response = app_client.call("POST", "/v1/agents/w1:p1/image", image_payload(PNG_BYTES, mime))
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "unsupported_type"


def test_an_image_whose_bytes_disagree_with_the_type_is_refused(app_client: Harness) -> None:
    response = app_client.call(
        "POST", "/v1/agents/w1:p1/image", image_payload(JPEG_BYTES, "image/png")
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "type_mismatch"


def test_invalid_base64_image_data_is_refused(app_client: Harness) -> None:
    response = app_client.call(
        "POST", "/v1/agents/w1:p1/image", {"mime": "image/png", "data": "!!not base64!!"}
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_image"


def test_a_bare_agent_name_is_refused_for_an_image(app_client: Harness) -> None:
    response = app_client.call(
        "POST", "/v1/agents/reviewer/image", image_payload(PNG_BYTES, "image/png")
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "bad_pane"


def test_a_refused_prompt_removes_the_stored_image(app_client: Harness) -> None:
    class Refusing:
        async def request(
            self, method: str, params: dict[str, Any] | None = None
        ) -> dict[str, Any]:
            raise HerdrError("agent.prompt: the agent is gone")

    app_client.context.client = Refusing()  # type: ignore[assignment]
    response = app_client.call(
        "POST", "/v1/agents/w1:p1/image", image_payload(PNG_BYTES, "image/png")
    )
    assert response.status_code == 409
    assert not app_client.images.exists() or not any(app_client.images.iterdir())


def test_an_image_for_a_gone_pane_is_a_404_and_leaves_no_file(app_client: Harness) -> None:
    app_client.context.client = GoneHerdr()  # type: ignore[assignment]
    response = app_client.call(
        "POST", "/v1/agents/wQ:pG/image", image_payload(PNG_BYTES, "image/png")
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "agent_not_found"
    assert not app_client.images.exists() or not any(app_client.images.iterdir())


def test_a_signature_does_not_transfer_to_another_path(app_client: Harness) -> None:
    """Path confusion: a reply must not be replayable as an approval."""
    body = json.dumps({"text": "sí"}).encode()
    headers = app_client.sign("POST", "/v1/agents/w1:p1/respond", body)
    response = app_client.client.post("/v1/agents/w1:p1/seen", content=body, headers=headers)
    assert response.status_code == 401


def test_there_is_no_http_enrollment_endpoint(app_client: Harness) -> None:
    """The only unauthenticated write in the API would be the hole.

    Adding a device is a host-side action. If it were reachable over HTTP then
    anything able to reach the port could register itself, and the public-key
    authentication above it would be theatre.
    """
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    payload = {
        "code": "ANYTHING",
        "curve": CURVE_P256,
        "public_key": base64.b64encode(public).decode(),
        "label": "attacker",
    }
    assert app_client.client.post("/v1/enroll", json=payload).status_code == 404


def test_no_unauthenticated_route_can_add_a_device(app_client: Harness) -> None:
    """Belt and braces: the only unauthenticated write is ``POST /v1/pair``.

    Fase 2(c) added that one route on purpose, gated by a host-printed code, a
    recovery code, or the tailnet-owner check. There is no bare enrollment route
    (``/v1/enroll``), and a pairing request without a valid proof adds nothing.
    """
    paths = {
        (frozenset(getattr(route, "methods", set()) or set()), getattr(route, "path", ""))
        for route in app_client.app.routes
    }
    assert (frozenset({"POST"}), "/v1/enroll") not in paths
    assert (frozenset({"POST"}), "/v1/pair") in paths

    before = len(app_client.devices)
    forged = {
        "curve": CURVE_P256,
        "public_key": base64.b64encode(
            ec.generate_private_key(ec.SECP256R1())
            .public_key()
            .public_bytes(
                serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
            )
        ).decode(),
        "label": "attacker",
        "code": "NOT-A-REAL-CODE",
    }
    response = app_client.client.post("/v1/pair", json=forged)
    assert response.status_code == 403
    assert len(app_client.devices) == before, "a refused pairing must not add a device"


def test_a_device_added_by_the_host_is_picked_up_without_a_restart(app_client: Harness) -> None:
    """The operator runs a CLI; a running server has to notice on its own."""
    second = NewPhone("second-phone")
    app_client.client.get("/v1/health")
    added = app_client.devices.add_device(
        curve=CURVE_P256,
        public_key=base64.b64encode(second.public_bytes()).decode(),
        label=second.label,
    )

    headers = second.signed("GET", "/v1/state", device_id=added.device_id)
    response = app_client.client.get("/v1/state", headers=headers)
    assert response.status_code == 200, "the new device should authenticate immediately"
    assert response.json()["counts"]["blocked"] == 1


def test_openapi_and_docs_are_not_served(app_client: Harness) -> None:
    """A generated schema is a map of the control plane for anyone who asks."""
    for path in ("/openapi.json", "/docs", "/redoc"):
        assert app_client.client.get(path).status_code == 404


# -- authorization (M2) -----------------------------------------------------


def test_a_read_only_device_reads_state(app_client: Harness) -> None:
    """The pairing default: a newly paired device may observe."""
    response = app_client.call_as(
        app_client.restricted, app_client.restricted_key, "GET", "/v1/state"
    )
    assert response.status_code == 200
    assert response.json()["counts"]["blocked"] == 1


def test_a_read_only_device_is_refused_on_the_act_endpoints(app_client: Harness) -> None:
    """A valid signature says who you are, not what you may do.

    Every act endpoint answers the same uniform 403: the reason is not sent to
    the caller, the same oracle reasoning as the uniform 401.
    """
    for path in (
        "/v1/agents/w1:p1/respond",
        "/v1/agents/w1:p1/keys",
        "/v1/agents/w1:p1/focus",
    ):
        response = app_client.call_as(
            app_client.restricted, app_client.restricted_key, "POST", path, {"text": "sí"}
        )
        assert response.status_code == 403, path
        assert response.json() == {"detail": "forbidden"}, path


def test_a_read_only_device_can_mark_an_agent_seen(app_client: Harness) -> None:
    """seen is non-destructive and reversible: READ_STATE is enough."""
    response = app_client.call_as(
        app_client.restricted, app_client.restricted_key, "POST", "/v1/agents/w1:p1/seen"
    )
    assert response.status_code == 200


def test_a_read_only_device_can_read_pane_output(app_client: Harness) -> None:
    """read mutates nothing: it sits behind READ_STATE, not RESPOND."""
    response = app_client.call_as(
        app_client.restricted,
        app_client.restricted_key,
        "POST",
        "/v1/agents/w1:p1/read",
        {"lines": 20},
    )
    assert response.status_code == 200
    assert response.json()["text"] == "output"


def test_a_new_chat_creates_a_workspace_and_starts_an_agent(app_client: Harness) -> None:
    """POST /v1/workspaces creates a workspace and starts an opencode agent in it."""
    response = app_client.call("POST", "/v1/workspaces", {"name": "de pruebas"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["pane_id"]
    assert payload["agent"]["agent"] == "opencode"
    methods = [m for m, _ in app_client.fake.requests]
    assert "workspace.create" in methods and "agent.start" in methods


def test_a_read_only_device_cannot_create_a_chat(app_client: Harness) -> None:
    """A new conversation is an act on agents: READ_STATE alone is not enough."""
    response = app_client.call_as(
        app_client.restricted,
        app_client.restricted_key,
        "POST",
        "/v1/workspaces",
        {"name": "de pruebas"},
    )
    assert response.status_code == 403


def test_a_read_only_device_is_self_served_on_its_own_token(app_client: Harness) -> None:
    """Self-service on the caller's own record needs no grant."""
    registration = "tok-123"
    response = app_client.call_as(
        app_client.restricted,
        app_client.restricted_key,
        "POST",
        "/v1/me/fcm-token",
        {"fcm_token": registration},
    )
    assert response.status_code == 200
    stored = app_client.devices.get(app_client.restricted.device_id)
    assert stored is not None and stored.fcm_token == registration


def test_a_host_grant_turns_a_read_only_device_into_an_authorized_one(app_client: Harness) -> None:
    """The grant path: the operator grants RESPOND, the phone can respond."""
    assert app_client.devices.grant(app_client.restricted.device_id, "respond") is True
    response = app_client.call_as(
        app_client.restricted,
        app_client.restricted_key,
        "POST",
        "/v1/agents/w1:p1/respond",
        {"text": "sí, hazlo"},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_a_revoked_device_is_401_not_403(app_client: Harness) -> None:
    """Revocation is an authentication failure; under-granting is not.

    The client must be able to tell "re-pair" from "you lack a grant", so a
    revoked device gets the 401 even on an endpoint it was never granted.
    """
    app_client.devices.revoke(app_client.restricted.device_id)
    response = app_client.call_as(
        app_client.restricted, app_client.restricted_key, "GET", "/v1/state"
    )
    assert response.status_code == 401


def test_an_unauthorized_request_leaves_no_trace(app_client: Harness) -> None:
    """A 403 happens before the rate limit and before last_seen is updated.

    An unauthorized request consumes no rate budget — it must not be able to
    waste the legitimate device's window — and leaves no last-seen trace, the
    same way a revoked device never reaches either.
    """
    before = app_client.context.limiter.used(app_client.restricted.device_id)
    response = app_client.call_as(
        app_client.restricted,
        app_client.restricted_key,
        "POST",
        "/v1/agents/w1:p1/respond",
        {"text": "sí"},
    )
    assert response.status_code == 403
    assert app_client.context.limiter.used(app_client.restricted.device_id) == before == {}
    stored = app_client.devices.get(app_client.restricted.device_id)
    assert stored is not None and stored.last_seen_at is None


def test_an_authorized_request_still_counts_against_the_budget(app_client: Harness) -> None:
    """Authorization does not bypass the rate limit that follows it."""
    assert app_client.devices.grant(app_client.restricted.device_id, "respond") is True
    for _ in range(3):
        response = app_client.call_as(
            app_client.restricted,
            app_client.restricted_key,
            "POST",
            "/v1/agents/w1:p1/respond",
            {"text": "sí"},
        )
        assert response.status_code == 200
    used = app_client.context.limiter.used(app_client.restricted.device_id)
    assert used.get("write") == 3


async def test_a_revoked_device_loses_its_live_stream(
    app_client: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Revocation reaches an established stream within one keepalive.

    Without this, a revoked phone keeps receiving live state until the stream
    happens to break: revocation would only refuse *new* requests, and the
    stream is the one long-lived request. The check runs before every frame —
    including keepalive comments — so nothing at all flows after the
    revocation.

    The TestClient cannot drive this: it buffers the whole response body, so a
    never-ending stream would block the request forever — which is why no other
    test opens /v1/events through it. A real uvicorn server on an ephemeral
    loopback port is what makes the claim observable: real HTTP, real SSE, real
    bytes.
    """
    import asyncio

    import httpx
    import uvicorn

    monkeypatch.setattr("herdr_notify.api.app.STREAM_KEEPALIVE_SECONDS", 0.2)
    server = uvicorn.Server(
        uvicorn.Config(app_client.app, host="127.0.0.1", port=0, log_level="warning")
    )
    serve_task = asyncio.create_task(server.serve())
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.05)
        assert server.started, "the server did not start"
        port = server.servers[0].sockets[0].getsockname()[1]

        opening = b""
        tail: list[bytes] = []
        revoked = False
        async with httpx.AsyncClient() as http:
            async with http.stream(
                "GET",
                f"http://127.0.0.1:{port}/v1/events",
                headers=app_client.sign("GET", "/v1/events"),
            ) as response:
                assert response.status_code == 200
                async for chunk in response.aiter_bytes():
                    if b"event: state" not in opening:
                        opening += chunk
                        if b"event: state" in opening:
                            # The opening frame has arrived and the stream
                            # generator is parked waiting for the next frame:
                            # revoke now.
                            revoked = app_client.devices.revoke(app_client.device.device_id)
                        continue
                    tail.append(chunk)
        assert revoked is True
        assert b"event: state" in opening
        # The stream closed within one keepalive of the revocation, and
        # nothing — no keepalive comment, no state frame — was delivered after.
        assert tail == []
    finally:
        server.should_exit = True
        await serve_task


def test_peers_requires_a_signature(app_client: Harness) -> None:
    assert app_client.client.get("/v1/peers").status_code == 401


def test_a_read_only_device_reads_the_peer_list(
    app_client: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The phone's peer list comes through the same read permission as state."""
    from herdr_notify.tailnet import parse_status

    view = parse_status(
        {
            "BackendState": "Running",
            "Self": {"DNSName": "pc-ejemplo.tail.ts.net.", "TailscaleIPs": ["100.64.0.1"]},
            "Peer": {
                "k": {
                    "DNSName": "tecno.tail.ts.net.",
                    "TailscaleIPs": ["100.64.0.2"],
                    "Online": True,
                }
            },
        }
    )
    monkeypatch.setattr("herdr_notify.api.app.read_tailnet_status", lambda: view)
    response = app_client.call_as(
        app_client.restricted, app_client.restricted_key, "GET", "/v1/peers"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["self"]["name"] == "pc-ejemplo"
    assert body["peers"][0]["addresses"] == ["100.64.0.2"]


def test_peers_is_503_when_tailscale_cannot_be_asked(
    app_client: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("herdr_notify.api.app.read_tailnet_status", lambda: None)
    assert app_client.call("GET", "/v1/peers").status_code == 503
