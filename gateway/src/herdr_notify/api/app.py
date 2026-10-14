"""The HTTP control plane.

Binds loopback only. The tailnet front end, not this process, is responsible for
being reachable from a phone, which keeps the "what is exposed" question
answerable by looking at one line of configuration.

Two rules shape the whole surface:

**The client names an action, never a herdr method.** See
:mod:`.actions`; a passthrough would expose the full agent-control surface to
anything that could reach the port.

**Every request is signed.** There is no bearer token to leak. The dependency in
:func:`require_device` is the only way into anything except enrollment, and it
runs before routing, so an unsigned request never reaches a handler.

**A signature is not an authorization.** Authentication answers who the caller
is; :mod:`.authz` answers what it may do, and an authenticated device without
the endpoint's grant receives a 403 rather than an implicit allowance.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, ValidationError

from ..herdr.client import HerdrClient, HerdrError
from ..notify.attention import counts, triage
from ..state.store import Store
from ..tailnet import read_status as read_tailnet_status
from ..tailnet import whois as tailnet_whois
from ..watcher import Watcher
from .actions import (
    READ_FALLBACK_SOURCE,
    ActionError,
    build_focus,
    build_read,
    build_respond,
    build_send_keys,
    validate_pane_id,
)
from .auth import (
    SUPPORTED_CURVES,
    AuthError,
    AuthorizationError,
    DeviceStore,
    EnrollmentRejected,
    RequestVerifier,
    VerifiedRequest,
    authorize,
)
from .images import (
    MAX_IMAGE_BODY_BYTES,
    ImageError,
    image_prompt,
    store_image,
)
from .ratelimit import RateLimiter, StreamRegistry

log = logging.getLogger(__name__)

#: Enrollment is the only unauthenticated write, and it needs a body. Kept
#: small: the only meaningful content is a public key and a label.
MAX_ENROLL_BODY = 8 * 1024

#: Upper bound on any signed body. The signing string hashes it, so it has to
#: be a known size before hashing rather than after.
MAX_SIGNED_BODY = 256 * 1024

#: Seconds between keepalive comments on the SSE stream. A module constant
#: rather than an inline literal so a test can shorten it: revocation reaching
#: an established stream is a behavioural claim, and waiting the real 20 s to
#: observe it would make the suite slower for no reason.
STREAM_KEEPALIVE_SECONDS: Final = 20.0

#: herdr error codes that mean "the pane this phone is addressing is gone".
#: herdr answers ``agent_not_found`` ("agent target wQ:pG not found") when a
#: chat is open for a pane that has since been closed; ``not_found`` is the
#: same answer spelled by older builds and by the test double.
AGENT_NOT_FOUND_CODES: Final = frozenset({"agent_not_found", "not_found"})


def _agent_not_found(exc: HerdrError) -> bool:
    """Whether herdr's refusal means the target pane no longer exists."""
    return exc.code in AGENT_NOT_FOUND_CODES


def _agent_gone(message: str) -> HTTPException:
    """A stable 404 the app branches on, rather than herdr's wording.

    The code is the contract, not the message: the phone stops polling and
    drops the agent on ``agent_not_found``, and a message it cannot parse
    would leave it showing a generic failure forever.
    """
    return HTTPException(
        status_code=404, detail={"code": "agent_not_found", "message": message}
    )


class ApiConfig(BaseModel):
    """Everything the app needs to know. Secrets are not among them."""

    device_store_path: Path = Path.home() / ".config" / "herdr-notify" / "devices.json"
    host: str = "127.0.0.1"
    port: int = 8787

    max_read_lines: int = 200
    image_store_dir: Path = Path.home() / ".config" / "herdr-notify" / "images"


class RespondRequest(BaseModel):
    text: str = Field(min_length=1)


class ImageRequest(BaseModel):
    mime: str = Field(min_length=1, max_length=64)
    data: str = Field(min_length=1)


class KeysRequest(BaseModel):
    keys: list[str] = Field(min_length=1, max_length=8)
    confirm: bool = False


class ReadRequest(BaseModel):
    lines: int | None = Field(default=None, ge=1, le=200)


class PairRequest(BaseModel):
    """The one unauthenticated write: pair a phone, or re-key it from recovery."""

    curve: str
    public_key: str = Field(min_length=1, max_length=512)
    label: str | None = Field(default=None, max_length=64)
    code: str | None = Field(default=None, max_length=64)


@dataclass(slots=True)
class AppContext:
    store: Store
    devices: DeviceStore
    verifier: RequestVerifier
    limiter: RateLimiter
    streams: StreamRegistry
    client: HerdrClient
    watcher: Watcher | None = None
    subscribers: set[asyncio.Queue[dict[str, Any]]] | None = None

    def publish(self, payload: dict[str, Any]) -> None:
        for queue in list(self.subscribers or ()):
            if queue.full():
                # A phone that stopped reading must not be able to grow the
                # gateway's memory; it re-syncs from /v1/state on reconnect.
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(payload)


def _raw_body(request: Request) -> bytes:
    """The exact bytes to hash into the signing string.

    Read from the stream rather than a parsed model: the signature covers what
    arrived, and a re-serialised model would be a second, differently-encoded
    copy of the same request.
    """
    cached = getattr(request.state, "herdr_notify_body", None)
    if cached is None:
        raise HTTPException(status_code=400, detail="body was not read before use")
    return cached  # type: ignore[no-any-return]


async def _capture_body(request: Request, limit: int = MAX_ENROLL_BODY) -> bytes:
    body = await request.body()
    if len(body) > limit:
        raise HTTPException(status_code=413, detail="body too large")
    request.state.herdr_notify_body = body
    return body


def _signed_body_limit(path: str) -> int:
    """The signed-body cap for an endpoint.

    The image route carries an encoded picture and needs a larger ceiling than
    the 256 KiB every other signed request is held to.
    """
    if path.startswith("/v1/agents/") and path.endswith("/image"):
        return MAX_IMAGE_BODY_BYTES
    return MAX_SIGNED_BODY


def _parse_signed_body[ModelT: BaseModel](request: Request, model: type[ModelT]) -> ModelT:
    """Validate the body model against the bytes that were signed.

    Not FastAPI's automatic model binding. That path re-reads the body and
    decides how to parse it from the Content-Type header, which produces a
    second view of the request: a correctly signed body sent without
    ``application/json`` would be rejected with a 422 despite a valid signature,
    and the failure would look like an auth problem rather than a header one.

    Parsing the exact bytes that were hashed keeps a single source of truth for
    what was signed and what is acted on.
    """
    try:
        return model.model_validate_json(_raw_body(request) or b"{}")
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_body", "errors": exc.errors(include_url=False)},
        ) from exc


def _source_ip(request: Request) -> str:
    client = request.client
    return client.host if client is not None else ""


def _owner_of(ip: str) -> str:
    """The tailnet owner of ``ip``, or ``""`` when Tailscale cannot say."""
    who = tailnet_whois(ip)
    return who.owner_id if who is not None else ""


def _is_host_owner(ip: str) -> bool:
    """True when ``ip`` belongs to the host's own tailnet owner.

    The pairing auto-approval check: a phone on the operator's own Tailscale
    account needs no code. A missing binary, a stopped daemon, a tagged node or
    a different account all answer False, so none of them can auto-pair.
    """
    view = read_tailnet_status()
    if view is None or view.self_peer is None or not view.self_peer.owner_id:
        return False
    who = tailnet_whois(ip)
    return who is not None and who.owner_id == view.self_peer.owner_id


def _empty_code_detail(ip: str) -> dict[str, str]:
    """Why a code-less pairing was refused, and the path that works.

    The caller already knows it sent no code, so saying so leaks nothing: with
    no code there is only the owner check, and it failed. The message stays
    about the caller's own request and never reports a tailnet owner, address or
    hostname. A loopback source is called out because the common cause is the
    local ``tailscale serve`` proxy, which makes every request look local.
    """
    if ip in {"127.0.0.1", "::1"}:
        message = (
            "no pairing code was provided and this request arrived from a local "
            "address, so it cannot be matched to the host's tailnet owner (a "
            "local proxy makes every request look local); run `herdr-notify "
            "enroll` on the host and enter the code"
        )
    else:
        message = (
            "no pairing code was provided and this address is not the host's "
            "tailnet owner; run `herdr-notify enroll` on the host and enter the code"
        )
    return {"code": "pairing_rejected", "message": message}


def create_app(
    ctx: AppContext,
    config: ApiConfig | None = None,
) -> FastAPI:
    """Build the ASGI app. The caller owns the lifecycle of watcher and client."""
    settings = config or ApiConfig()

    app = FastAPI(
        title="herdr-notify",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.ctx = ctx
    app.state.config = settings

    @app.middleware("http")
    async def _trace_requests(request: Request, call_next: Any) -> Response:
        """Log every call the phone makes, so a no-op route still leaves a trace.

        ``/seen`` deliberately does not reach herdr, which is exactly why an
        investigation into "opening a chat moves the terminal focus" needs the
        *HTTP* request logged as well as the herdr call: the method the phone
        sent is the only evidence that the old focus-clearing path was involved.
        """
        response = await call_next(request)
        log.info("http %s %s -> %s", request.method, request.url.path, response.status_code)
        return response

    @app.exception_handler(AuthError)
    async def _auth_error(_: Request, exc: AuthError) -> JSONResponse:
        # One message for every rejection, so the endpoint cannot be used to
        # discover which device ids exist. The specific reason goes to the log.
        log.info("refused a signed request: %s", exc.rejection)
        return JSONResponse({"detail": exc.public_message}, status_code=401)

    @app.exception_handler(AuthorizationError)
    async def _authz_error(request: Request, exc: AuthorizationError) -> JSONResponse:
        # One message for every authorization rejection, mirroring the uniform
        # 401: the reason is not sent to the caller. The specific reason, the
        # device id and the required permission go to the log — the audit
        # trail. At 403-time the device is authenticated, so its header id is
        # real, unlike a 401 where the caller may have fabricated it.
        log.info(
            "refused an authorized request from %s: %s (required: %s)",
            request.headers.get("x-hn-device", "?"),
            exc.rejection,
            exc.required.value if exc.required is not None else "-",
        )
        return JSONResponse({"detail": exc.public_message}, status_code=403)

    async def require_device(
        request: Request,
        x_hn_device: str = Header(default=""),
        x_hn_timestamp: str = Header(default=""),
        x_hn_nonce: str = Header(default=""),
        x_hn_signature: str = Header(default=""),
    ) -> VerifiedRequest:
        headers = {
            "X-HN-Device": x_hn_device,
            "X-HN-Timestamp": x_hn_timestamp,
            "X-HN-Nonce": x_hn_nonce,
            "X-HN-Signature": x_hn_signature,
        }
        body_limit = _signed_body_limit(request.url.path)
        body = await _capture_body(request, limit=body_limit)
        # The trust store can be rewritten by a host-side CLI while this server
        # runs, so pick that up before deciding whether the device is known.
        ctx.devices.reload_if_changed()
        target = request.scope.get("raw_path", request.url.path).decode("latin-1")
        verified = ctx.verifier.verify(
            method=request.method,
            # The raw target, query string included, exactly as the phone signed
            # it. Reassembling it from routing would be a second, differently
            # spelled path.
            target=target,
            body=body,
            headers=headers,
            max_body_bytes=body_limit,
        )
        # Authorization is a separate question from authentication: the
        # signature says who the caller is, not what it may do. Checked after
        # authentication and before the rate limit, so an unauthorized request
        # consumes no rate budget and leaves no last-seen trace — the same way
        # a revoked device never reaches either.
        authorize(verified.device, method=request.method, target=target)
        allowed, retry_after = ctx.limiter.allow(verified.device_id, write=False)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="slow down",
                headers={"Retry-After": str(int(retry_after) + 1)},
            )
        ctx.devices.touch(verified.device_id)
        return verified

    def require_write(verified: VerifiedRequest) -> None:
        allowed, retry_after = ctx.limiter.allow(verified.device_id, write=True)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="slow down",
                headers={"Retry-After": str(int(retry_after) + 1)},
            )

    async def perform(action: Any) -> dict[str, Any]:
        method, params = action.method_params()
        try:
            return await ctx.client.request(method, params)
        except HerdrError as exc:
            # herdr's own refusal is a legitimate answer, not a gateway fault:
            # an agent that is no longer blocked, or a prompt herdr declined.
            log.info("herdr refused %s: %s", method, exc)
            if _agent_not_found(exc):
                # The pane is gone rather than unwilling: a chat left open for
                # an agent the operator closed on the PC. 409 would tell the
                # phone to keep waiting for a state that cannot come back.
                raise _agent_gone(str(exc)) from exc
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    def act_or_400(builder: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return builder(*args, **kwargs)
        except ActionError as exc:
            raise HTTPException(
                status_code=400, detail={"code": exc.code, "message": exc.message}
            ) from exc

    # -- health, deliberately unauthenticated -------------------------------

    @app.get("/v1/health")
    async def health() -> dict[str, Any]:
        """Liveness, with nothing an attacker could use.

        herdr's version and pane counts are not exposed here: an unauthenticated
        endpoint that describes the operator's machine is reconnaissance.
        """
        state = ctx.store.state
        return {
            "ok": state.version is not None,
            "revision": state.revision,
            "devices": len(ctx.devices),
            "streams": ctx.streams.total,
        }

    # -- pairing, the one unauthenticated write -----------------------------

    @app.post("/v1/pair")
    async def pair(request: Request) -> dict[str, Any]:
        """Pair a phone: from a host-printed code, a recovery code, or ownership.

        The only write reachable without a signature — a signature cannot exist
        yet, because the phone holds no key the gateway trusts. Authorisation is
        therefore a single-use code the operator reads off this machine, a
        per-device recovery code, or, when the source address is on the
        operator's own tailnet account, that ownership. Never a static secret.

        The response carries the recovery code exactly once; only its hash is
        stored. Everything else the phone already knows or does not need.
        """
        body = await _capture_body(request)
        try:
            payload = PairRequest.model_validate_json(body or b"{}")
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail="invalid_body") from exc
        if payload.curve not in SUPPORTED_CURVES:
            raise HTTPException(status_code=400, detail="invalid_body")

        ip = _source_ip(request)
        allowed, retry_after = ctx.limiter.allow(f"pair:{ip}", write=True)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="slow down",
                headers={"Retry-After": str(int(retry_after) + 1)},
            )

        ctx.devices.reload_if_changed()
        owner = _owner_of(ip)
        label = payload.label

        if payload.code:
            # A pairing code first: it is the common case and its format never
            # collides with a recovery code.
            try:
                device = ctx.devices.enroll(
                    code=payload.code,
                    curve=payload.curve,
                    public_key=payload.public_key,
                    label=label,
                    owner_id=owner,
                )
            except EnrollmentRejected:
                try:
                    device, rotated = ctx.devices.use_recovery_code(
                        code=payload.code,
                        curve=payload.curve,
                        public_key=payload.public_key,
                        label=label,
                        owner_id=owner,
                    )
                except EnrollmentRejected as exc:
                    raise HTTPException(status_code=403, detail="pairing_rejected") from exc
                return _pair_response(device, rotated)
            recovery = ctx.devices.issue_recovery_code(device.device_id) or ""
            return _pair_response(device, recovery)

        # No code: the same tailnet owner is the proof. Anything else is refused
        # uniformly, so an address cannot be probed for whose account owns it.
        if not _is_host_owner(ip):
            raise HTTPException(status_code=403, detail=_empty_code_detail(ip))
        device = ctx.devices.add_device(
            curve=payload.curve,
            public_key=payload.public_key,
            label=label,
            owner_id=owner,
        )
        recovery = ctx.devices.issue_recovery_code(device.device_id) or ""
        return _pair_response(device, recovery)

    # -- state -------------------------------------------------------------

    @app.get("/v1/state")
    async def read_state(verified: VerifiedRequest = Depends(require_device)) -> dict[str, Any]:
        del verified
        return state_payload(ctx)

    @app.get("/v1/peers")
    async def peers(verified: VerifiedRequest = Depends(require_device)) -> dict[str, Any]:
        """The host's view of the tailnet, for the phone to probe in parallel.

        Signed like every read: only a paired device with ``read_state`` gets
        the list. The gateway is bound inside the tailnet (see ``bind_sockets``),
        so nothing outside it can reach this route at all.
        """
        del verified
        view = read_tailnet_status()
        if view is None:
            raise HTTPException(status_code=503, detail="tailscale unavailable")
        return view.to_json()

    @app.get("/v1/events")
    async def events(verified: VerifiedRequest = Depends(require_device)) -> Response:
        """Live state over SSE.

        Authenticated once, at connect, the same as any other request. The
        per-device stream cap stops a phone that reconnects in a loop from
        holding an unbounded number of workers and herdr subscriptions.
        """
        if not ctx.streams.acquire(verified.device_id):
            raise HTTPException(status_code=429, detail="too many open streams")

        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        subscribers = ctx.subscribers if ctx.subscribers is not None else set()
        if ctx.subscribers is None:
            ctx.subscribers = subscribers
        subscribers.add(queue)

        async def stream() -> AsyncIterator[bytes]:
            try:
                # A full state frame first, so a client that connects while
                # events are queued still converges without a second round trip.
                payload = opening_state_frame(ctx)
                yield f"event: state\ndata: {payload}\n\n".encode()
                while True:
                    try:
                        message = await asyncio.wait_for(
                            queue.get(), timeout=STREAM_KEEPALIVE_SECONDS
                        )
                    except TimeoutError:
                        # The trust store can change under a running server (a
                        # host-side revoke), and the stream is the only path a
                        # phone holds open — no other request will come along
                        # and trigger the reload. Without picking the change up
                        # here, the check below would read a stale trust list
                        # and a revoked phone would keep receiving state.
                        ctx.devices.reload_if_changed()
                        # Revocation is checked before even a keepalive comment,
                        # so nothing at all flows to a device that has been
                        # revoked while it sat watching — not just no state.
                        if ctx.devices.get_trusted(verified.device_id) is None:
                            break
                        # Comment frames keep intermediaries from timing the
                        # connection out.
                        yield b": keepalive\n\n"
                        continue
                    # And before every state frame: a revocation recorded while
                    # this frame was queued must not be delivered to the device
                    # it revoked. Without this, revocation would only refuse
                    # *new* requests, and the stream is the one long-lived one.
                    ctx.devices.reload_if_changed()
                    if ctx.devices.get_trusted(verified.device_id) is None:
                        break
                    body = json.dumps(message, ensure_ascii=False)
                    yield f"event: {message.get('event', 'change')}\ndata: {body}\n\n".encode()
            finally:
                subscribers.discard(queue)
                ctx.streams.release(verified.device_id)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    # -- actions -----------------------------------------------------------

    @app.post("/v1/agents/{pane_id}/respond")
    async def respond(
        pane_id: str, request: Request, verified: VerifiedRequest = Depends(require_device)
    ) -> dict[str, Any]:
        require_write(verified)
        payload = _parse_signed_body(request, RespondRequest)
        result = await perform(act_or_400(build_respond, pane_id, payload.text))
        return {"ok": True, "result": _summarise(result)}

    @app.post("/v1/agents/{pane_id}/keys")
    async def keys(
        pane_id: str, request: Request, verified: VerifiedRequest = Depends(require_device)
    ) -> dict[str, Any]:
        require_write(verified)
        payload = _parse_signed_body(request, KeysRequest)
        result = await perform(
            act_or_400(build_send_keys, pane_id, payload.keys, confirm=payload.confirm)
        )
        return {"ok": True, "result": _summarise(result)}

    @app.post("/v1/agents/{pane_id}/focus")
    async def focus(
        pane_id: str, verified: VerifiedRequest = Depends(require_device)
    ) -> dict[str, Any]:
        require_write(verified)
        result = await perform(act_or_400(build_focus, pane_id))
        return {"ok": True, "result": _summarise(result)}

    @app.post("/v1/agents/{pane_id}/seen")
    async def mark_seen(
        pane_id: str, verified: VerifiedRequest = Depends(require_device)
    ) -> dict[str, Any]:
        """Acknowledge a completion without touching the host.

        herdr 0.9.1 has no way to clear an agent's "done" badge that is separate
        from focus: ``agent.focus`` is the only call that marks a pane seen, and
        it also moves the operator's focus in the terminal. Opening a chat on the
        phone must not move focus on the PC, so the phone marks the agent seen in
        the app and this route no longer reaches herdr at all. It stays as an
        acknowledged no-op for clients that still call it.
        """
        del verified
        target = act_or_400(validate_pane_id, pane_id)
        if target not in ctx.store.state.agents:
            # This route never reaches herdr, so herdr cannot be the one to say
            # the pane is gone — the gateway's own mirror is. The answer is the
            # same 404 and the same code as the routes that do call herdr, so a
            # phone sees one meaning for "this agent no longer exists".
            raise _agent_gone(f"agent target {target} not found")
        return {"ok": True, "pane_id": target}

    @app.post("/v1/agents/{pane_id}/read")
    async def read_agent(
        pane_id: str, request: Request, verified: VerifiedRequest = Depends(require_device)
    ) -> dict[str, Any]:
        require_write(verified)
        payload = _parse_signed_body(request, ReadRequest)
        action = act_or_400(build_read, pane_id, payload.lines)
        try:
            result = await perform(action)
        except HTTPException as exc:
            # herdr refuses the history source while the pane is on its
            # alternate screen (a working full-screen agent): that history can
            # only be captured by scrolling while idle. The visible screen is
            # always available, so fall back to it rather than answering the
            # phone with a 409 it can only render as a generic read failure.
            if exc.status_code != 409:
                raise
            log.info("read: %s refused the history source, using the visible screen", pane_id)
            fallback = act_or_400(
                build_read, pane_id, payload.lines, source=READ_FALLBACK_SOURCE
            )
            result = await perform(fallback)
        read = result.get("read") or {}
        return {
            "text": read.get("text", ""),
            "pane_id": read.get("pane_id", pane_id),
        }

    @app.post("/v1/agents/{pane_id}/image")
    async def send_image(
        pane_id: str, request: Request, verified: VerifiedRequest = Depends(require_device)
    ) -> dict[str, Any]:
        """Accept an image for an agent and hand it the file path.

        The picture is written under the gateway's own data dir and the agent is
        sent a prompt naming the absolute path, so the agent opens it with the
        tools it already has. The file is removed again if herdr refuses the
        prompt, so a rejected attachment leaves nothing behind.
        """
        require_write(verified)
        payload = _parse_signed_body(request, ImageRequest)
        target = act_or_400(validate_pane_id, pane_id)
        try:
            stored = store_image(settings.image_store_dir, target, payload.mime, payload.data)
        except ImageError as exc:
            raise HTTPException(
                status_code=400, detail={"code": exc.code, "message": exc.message}
            ) from exc
        try:
            result = await perform(act_or_400(build_respond, target, image_prompt(stored.path)))
        except HTTPException:
            with contextlib.suppress(OSError):
                stored.path.unlink()
            raise
        return {
            "ok": True,
            "pane_id": target,
            "path": str(stored.path),
            "result": _summarise(result),
        }

    # -- new conversation ----------------------------------------------------

    class NewChatRequest(BaseModel):
        name: str = Field(min_length=1, max_length=64)
        cwd: str | None = Field(default=None, max_length=512)

    @app.post("/v1/workspaces")
    async def new_chat(
        request: Request, verified: VerifiedRequest = Depends(require_device)
    ) -> dict[str, Any]:
        """Start a fresh conversation: one workspace, one opencode agent."""
        require_write(verified)
        try:
            payload = NewChatRequest.model_validate(json.loads(_raw_body(request) or b"{}"))
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="invalid body") from exc

        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="name is required")
        if any(ord(c) < 32 for c in name):
            raise HTTPException(status_code=400, detail="name contains control characters")

        params: dict[str, Any] = {"label": name}
        if payload.cwd:
            params["cwd"] = payload.cwd
        try:
            created = await ctx.client.request("workspace.create", params)
        except HerdrError as exc:
            log.info("herdr refused workspace.create: %s", exc)
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        root = (created.get("root_pane") or {}) if isinstance(created, dict) else {}
        pane_id = root.get("pane_id")
        if not isinstance(pane_id, str) or not pane_id:
            raise HTTPException(status_code=502, detail="herdr returned no pane_id")

        try:
            started = await ctx.client.request(
                "agent.start",
                {"name": name, "kind": "opencode", "pane": pane_id},
            )
        except HerdrError as exc:
            log.info("herdr refused agent.start: %s", exc)
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        agent = started.get("agent") if isinstance(started, dict) else None
        workspace = created.get("workspace", {}) if isinstance(created, dict) else {}
        return {
            "ok": True,
            "workspace_id": workspace.get("workspace_id") if isinstance(workspace, dict) else None,
            "pane_id": pane_id,
            "agent": agent or {"agent": "opencode", "agent_status": "idle", "pane_id": pane_id},
        }

    # -- device self-service ------------------------------------------------

    @app.post("/v1/me/fcm-token")
    async def set_fcm_token(
        request: Request, verified: VerifiedRequest = Depends(require_device)
    ) -> dict[str, Any]:
        """Attach or replace this device's FCM token.

        Separate from enrollment because FCM rotates the token on reinstall and
        on some app updates. A phone that can only register once would silently
        stop receiving pushes after its first update.
        """
        require_write(verified)
        # The auth dependency already read and hashed the exact bytes.
        raw = _raw_body(request)
        try:
            token = str(json.loads(raw or b"{}").get("fcm_token") or "")[:512]
        except (json.JSONDecodeError, AttributeError) as exc:
            raise HTTPException(status_code=400, detail="invalid body") from exc
        if not token:
            raise HTTPException(status_code=400, detail="fcm_token is required")
        ctx.devices.set_fcm_token(verified.device_id, token)
        return {"ok": True}

    # -- device management ("My devices", ADMIN) ---------------------------

    @app.get("/v1/devices")
    async def list_devices(
        verified: VerifiedRequest = Depends(require_device),
    ) -> dict[str, Any]:
        """Every paired device, for the "My devices" screen.

        Behind ``admin``: knowing the device roster is management visibility, not
        something a read-only phone needs. Public material only — never a public
        key or an FCM token.
        """
        del verified
        return {"ok": True, "devices": [d.to_public() for d in ctx.devices.list()]}

    @app.post("/v1/devices/{device_id}/revoke")
    async def revoke_device(
        device_id: str, verified: VerifiedRequest = Depends(require_device)
    ) -> dict[str, Any]:
        """Revoke one device; its next signed request is a 401.

        Behind ``admin`` and the write budget. Revocation marks rather than
        deletes, so the record stays visible and auditable. Because
        ``RequireDevice`` checks ``revoked`` before any cryptography, the device
        is refused on every endpoint and on any stream it holds open.
        """
        require_write(verified)
        if not ctx.devices.revoke(device_id):
            raise HTTPException(status_code=404, detail="no such device")
        return {"ok": True, "device_id": device_id, "revoked": True}

    return app


def _pair_response(device: Any, recovery: str) -> dict[str, Any]:
    """The pairing response: identity, grants, owner, and the recovery code.

    The recovery code is the one secret in this payload and is returned exactly
    once. Only a hash is persisted, so this is the only moment it can be shown.
    """
    return {
        "ok": True,
        "device_id": device.device_id,
        "curve": device.curve,
        "label": device.label,
        "permissions": sorted(device.permissions),
        "owner_id": device.owner_id,
        "recovery_code": recovery,
    }


def state_payload(ctx: AppContext) -> dict[str, Any]:
    """The one state read model.

    Served by ``GET /v1/state`` and by the opening frame of the SSE stream, and
    deliberately built in exactly one place. The two paths used to answer
    differently: the SSE frame returned the raw reduced view, whose agent entries
    carry no ``attention`` and whose ``counts`` tallies collections rather than
    statuses, while ``/v1/state`` returned ranked triage rows. The app therefore
    ranked from a payload the gateway never ranked, and the two endpoints could
    disagree about the same session.

    A second shape for one concept is a contract break, not a convenience.
    """
    view = ctx.store.state.view()
    rows = triage(view)
    return {
        "revision": view["revision"],
        "herdr_version": view["herdr_version"],
        "focused": view["focused"],
        "counts": counts(rows),
        "agents": [row.to_public() for row in rows],
    }


def opening_state_frame(ctx: AppContext) -> str:
    """The ``data`` payload of the SSE stream's first frame.

    Factored out so the shape it promises can be pinned by a test without
    driving a never-ending stream through the test client, and so the stream
    cannot quietly drift back to a second state shape.
    """
    state = state_payload(ctx)
    return json.dumps(
        {"event": "state", "revision": state["revision"], "state": state},
        ensure_ascii=False,
    )


def _summarise(result: dict[str, Any]) -> dict[str, Any]:
    """Trim a herdr response to what the app needs.

    herdr's success payloads embed the full agent record. Returning it wholesale
    would publish fields the app has no use for and keep the response shape
    coupled to a protocol the app does not depend on.
    """
    agent = result.get("agent")
    if isinstance(agent, dict):
        return {
            "pane_id": agent.get("pane_id"),
            "agent": agent.get("agent"),
            "agent_status": agent.get("agent_status"),
        }
    return {"type": result.get("type")}


__all__ = [
    "ApiConfig",
    "AppContext",
    "create_app",
    "opening_state_frame",
    "state_payload",
]
