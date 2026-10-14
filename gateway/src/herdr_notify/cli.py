"""Command line entry points.

``dump`` is the F1/F2 gate: it proves the client can talk to a live herdr
server, reduce the snapshot and hold a live subscription. It only ever calls
read-only herdr methods.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import signal
import socket
import sys
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .herdr.paths import Endpoint, is_pid_lock_file
from .notify.fcm import Device, DeviceRegistry
from .state.store import AgentChange, Store
from .watcher import Watcher

log = logging.getLogger("herdr_notify.cli")

_STATUS_GLYPH = {
    "blocked": "!",
    "working": "*",
    "done": "+",
    "idle": "-",
    "unknown": "?",
}


class StoreBackedRegistry(DeviceRegistry):
    """The push sender's delivery view over the trust store.

    The trust store is where a token lives (push.md): the registration endpoint
    writes it there, revocation clears it there. Reading it at send time means
    a registration, a rotation and a revocation all reach the next send without
    a second copy of the truth — the same property M2 gave the stream, where a
    revoked device stops receiving frames within one keepalive. A restart costs
    nothing: the store persisted what an in-memory ledger would have lost.

    The outcome bookkeeping (``note_success``/``note_failure``) stays a
    per-process diagnostic; the token's home is the store.
    """

    def __init__(self, devices: Any) -> None:
        super().__init__()
        self._devices_store = devices

    def all(self) -> list[Device]:
        # The store can be rewritten by the host CLI while this runs; pick that
        # up before deciding whom to send to — the same way the stream does.
        self._devices_store.reload_if_changed()
        return [
            Device(device_id=d.device_id, token=d.fcm_token or "", label=d.label)
            for d in self._devices_store.list()
            if d.fcm_token and not d.revoked
        ]

    def prune(self, tokens: Iterable[str]) -> int:
        """Drop tokens Google reported as permanently dead — from the store.

        The in-memory ledger would forget them on restart and re-seed the dead
        token from the store on the next start, retrying a send that can never
        succeed once per push. Clearing it at the source ends that loop.
        """
        dead = set(tokens)
        if not dead:
            return 0
        pruned = 0
        for record in self._devices_store.list():
            if record.fcm_token in dead:
                self._devices_store.clear_fcm_token(record.device_id)
                pruned += 1
        return pruned


def _configure_logging(verbose: int) -> None:
    level = logging.WARNING if verbose == 0 else logging.INFO if verbose == 1 else logging.DEBUG
    logging.basicConfig(level=level, format="%(levelname)-7s %(name)s: %(message)s")
    # Always-on tracing of what the gateway sends to herdr and what the phone
    # asks for. These are the two facts a "the terminal moved on its own"
    # investigation needs, and the supervised service runs at WARNING, so an
    # INFO-by-default level for exactly these two loggers keeps the trace
    # reachable without turning on DEBUG for everything else.
    for name in ("herdr_notify.herdr.client", "herdr_notify.api.app"):
        logging.getLogger(name).setLevel(logging.INFO)


def _cmd_doctor(args: argparse.Namespace) -> int:
    """Report whether the resolved endpoint looks reachable, without connecting."""
    try:
        endpoint = Endpoint.resolve(args.session)
    except Exception as exc:
        print(f"endpoint resolution failed: {exc}", file=sys.stderr)
        return 2

    print(f"platform       : {sys.platform}")
    print(f"python         : {sys.version.split()[0]}")
    print(f"herdr config   : {endpoint.path.parent}")
    print(f"endpoint path  : {endpoint.path}")
    print(f"transport      : {'named pipe' if endpoint.is_named_pipe else 'unix socket'}")
    if is_pid_lock_file(endpoint.path):
        print("note           : that path is herdr's PID lock file, not a socket")
    print(f"probe          : {endpoint.describe()}")

    if args.ping:

        async def _ping() -> int:
            from .herdr.client import HerdrClient, HerdrError

            client = HerdrClient(endpoint)
            try:
                result = await client.ping()
            except HerdrError as exc:
                print(f"ping           : FAILED — {exc}")
                return 1
            capabilities = result.get("capabilities") or {}
            print(
                f"ping           : ok — herdr {result.get('version')} "
                f"protocol {result.get('protocol')}"
            )
            print(f"capabilities   : {', '.join(sorted(capabilities)) or 'none reported'}")
            return 0

        return asyncio.run(_ping())
    return 0


_SERVICE_TASK = "herdr-notify-gateway"


def _gateway_log_path() -> Path:
    """The supervised gateway's log, matching run-gateway-supervised.ps1."""
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / ".local" / "share"
    return root / "herdr-notify" / "gateway.log"


def _device_totals(devices: Iterable[Any]) -> tuple[int, int, int]:
    """Reduce a trust-store listing to (total, active, revoked)."""
    total = active = revoked = 0
    for device in devices:
        total += 1
        if device.revoked:
            revoked += 1
        else:
            active += 1
    return total, active, revoked


def _port_listening(host: str, port: int, timeout: float = 0.5) -> bool:
    """True when something accepts a loopback connection on host:port.

    A connect attempt is the one probe that cannot lie: a listening socket is
    the gateway, and nothing at all is the gateway not being up.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _cmd_status(args: argparse.Namespace) -> int:
    """Report the PC-side view: endpoint, trust store, gateway and logs.

    Read-only and offline by design, so it stays useful when herdr is down. The
    service task's own state lives in tooling/herdr-notify-service.ps1 status;
    what matters here is whether a gateway is actually answering on the port.
    """
    from .api.auth import DeviceStore
    from .tailnet import read_status

    print(f"platform       : {sys.platform}")
    print(f"python         : {sys.version.split()[0]}")

    try:
        endpoint = Endpoint.resolve(args.session)
        print(f"herdr endpoint : {endpoint.describe()}")
    except Exception as exc:
        print(f"herdr endpoint : FAILED — {exc}")

    try:
        devices = DeviceStore(args.devices)
        total, active, revoked = _device_totals(devices.list())
        print(f"trust store    : {devices.path or args.devices}")
        print(f"devices        : {total} enrolled, {active} active, {revoked} revoked")
    except Exception as exc:
        print(f"trust store    : FAILED — {exc}")

    reach = "127.0.0.1"
    if _port_listening(reach, args.port):
        print(f"gateway        : listening on {reach}:{args.port}")
    else:
        print(f"gateway        : not listening on {reach}:{args.port}")

    view = read_status()
    if view is not None and view.self_peer is not None and view.self_peer.addresses:
        print(f"tailscale      : {', '.join(view.self_peer.addresses)} ({view.backend_state})")
    else:
        print("tailscale      : unavailable")

    print(f"log            : {_gateway_log_path()}")
    print()
    print(f"service        : tooling\\herdr-notify-service.ps1 status  ({_SERVICE_TASK})")
    return 0


def _render_watch(store: Store) -> str:
    view = store.state.view()
    lines: list[str] = []
    counts = view["counts"]
    lines.append(
        f"herdr {view['herdr_version']} · revision {view['revision']} · "
        f"{counts['workspaces']} workspaces · {counts['panes']} panes · {counts['agents']} agents"
    )
    lines.append("")
    order = {"blocked": 0, "done": 1, "working": 2, "unknown": 3, "idle": 4}
    agents = sorted(
        view["agents"],
        key=lambda a: (order.get(a["status"], 9), a["project"] or "", a["pane_id"]),
    )
    if not agents:
        lines.append("no coding agents detected in any pane")
        return "\n".join(lines)

    width = max((len(a["project"] or "?") for a in agents), default=4)
    for agent in agents:
        glyph = _STATUS_GLYPH.get(agent["status"], "?")
        marker = ">" if agent["focused"] else " "
        title = agent["title"] or "(no terminal title)"
        resume = " [resumable]" if agent["can_resume"] else ""
        lines.append(
            f"{marker} {glyph} {agent['status']:<7} {agent['project'] or '?':<{width}}  "
            f"{agent['agent'] or 'agent':<10} {agent['pane_id']:<6} {title}{resume}"
        )
    return "\n".join(lines)


def _cmd_dump(args: argparse.Namespace) -> int:
    store = Store()
    watcher = Watcher(session=args.session, store=store, request_timeout=args.timeout)

    last_revision = -1
    last_render = 0.0

    def _on_snapshot(view: dict[str, Any]) -> None:
        nonlocal last_revision, last_render
        if view["revision"] == last_revision:
            return
        last_revision = view["revision"]
        if args.follow and time.monotonic() - last_render < args.interval:
            return
        last_render = time.monotonic()
        if not args.json:
            print(_render_watch(store))
            print("", flush=True)
        else:
            print(json.dumps(view, ensure_ascii=False, indent=2), flush=True)

    async def _run() -> int:
        loop = asyncio.get_running_loop()
        stop = asyncio.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError, ValueError):
                loop.add_signal_handler(sig, stop.set)

        task = asyncio.create_task(watcher.start())
        try:
            await asyncio.wait_for(watcher.booted.wait(), args.boot_timeout)
        except TimeoutError:
            print("timed out waiting for the first herdr snapshot", file=sys.stderr)
            task.cancel()
            return 1

        _on_snapshot(store.state.view())
        if not args.follow:
            await watcher.stop()
            return 0

        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), args.interval)
            except TimeoutError:
                pass
            _on_snapshot(store.state.view())
        await watcher.stop()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        return 0

    return asyncio.run(_run())


def _cmd_schema(args: argparse.Namespace) -> int:
    """Emit the subscription set the watcher will build, for debugging."""
    from .herdr.client import UNSCOPED_EVENTS, build_subscriptions

    panes = sorted(args.pane or [])
    payload = {
        "unscoped_events": list(UNSCOPED_EVENTS),
        "subscriptions": build_subscriptions(panes),
    }
    print(json.dumps(payload, indent=2))
    return 0


def _cmd_add_device(args: argparse.Namespace) -> int:
    """Register a phone by its public key.

    The intended way to add a device, and the only one: a human runs this on
    the machine that runs the gateway. There is no HTTP enrollment endpoint,
    because an unauthenticated write inside a control plane that drives coding
    agents is a hole shaped exactly like the thing it protects.

    Get ``--public-key`` from the phone's pairing screen, which shows it as
    base64 together with the curve. Without ``--permission`` the device is
    paired with READ_STATE and nothing else; the act grants are host-side
    commands, exactly like this one.
    """
    from .api.auth import CURVE_P256, DeviceStore, EnrollmentRejected

    store = DeviceStore(args.devices)
    curve = args.curve
    if curve not in (CURVE_P256, "ed25519"):
        print(f"unsupported curve: {curve}", file=sys.stderr)
        return 2
    try:
        device = store.add_device(
            curve=curve,
            public_key=args.public_key,
            label=args.label,
            fcm_token=args.fcm_token,
            device_id=args.device_id,
            permissions=args.permission,
        )
    except EnrollmentRejected as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    print(f"device_id : {device.device_id}")
    print(f"curve     : {device.curve}")
    print(f"label     : {device.label or '-'}")
    print(f"permissions: {','.join(device.permissions) or '-'}")
    print(f"trust store: {store.path}")
    print()
    print("A running gateway picks this up on the next request; no restart needed.")
    return 0


def _print_qr(rendered: str) -> None:
    """Print the block art, falling back to raw UTF-8 on a legacy console.

    Windows PowerShell 5.1 can leave stdout on a code page without the block
    characters. Writing UTF-8 bytes keeps the symbol intact for a terminal that
    decodes it (Windows Terminal does) rather than crashing the command after
    the pairing code was already printed.
    """
    text = rendered + "\n"
    try:
        sys.stdout.write(text)
    except UnicodeEncodeError:
        sys.stdout.flush()
        sys.stdout.buffer.write(text.encode("utf-8"))
    sys.stdout.flush()


def _resolve_qr_url(args: argparse.Namespace, view: Any) -> tuple[str | None, int]:
    """The gateway base URL for ``--qr``, or a clear failure for the operator.

    Returns ``(url, 0)`` on success and ``(None, 2)`` when no source knows a
    reachable URL. The sources are, in order, ``--url``, the
    ``HERDR_NOTIFY_PUBLIC_URL`` environment variable, ``gateway.json`` next to
    the trust store, and the host's own tailnet address.
    """
    from .pairing import PUBLIC_URL_ENV, PairingPayloadError, resolve_public_url

    try:
        url = resolve_public_url(args.url, tailnet=view)
    except PairingPayloadError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return None, 2
    if url is not None:
        return url, 0

    print("error: --qr needs the gateway's public base URL.", file=sys.stderr)
    print(
        "  pass --url https://<host> (e.g. https://pc.tailnet.ts.net), or set",
        file=sys.stderr,
    )
    print(
        f"  {PUBLIC_URL_ENV}, or put {{\"public_url\": \"...\"}} in gateway.json next to",
        file=sys.stderr,
    )
    print(
        "  the trust store. The host's tailnet address is used when it is known.",
        file=sys.stderr,
    )
    return None, 2


def _cmd_enroll(args: argparse.Namespace) -> int:
    """Mint a single-use pairing code for a phone.

    The code is printed here, on the operator's own machine, and is the only
    thing that authorises a new device. There is no static secret to distribute.

    With ``--qr`` the same code is also encoded into the payload a phone scans,
    together with the gateway's base URL. Without ``--qr`` the output is
    unchanged: the code alone, which the phone's pairing screen accepts.
    """
    from .api.auth import DeviceStore
    from .pairing import build_pairing_payload, render_qr_ascii
    from .tailnet import read_status

    store = DeviceStore(args.devices)
    view = read_status()

    # Resolve the QR URL before minting: a missing URL is the operator's to fix,
    # and it should not leave a live code behind that nothing was told about.
    qr_url: str | None = None
    if args.qr:
        qr_url, code = _resolve_qr_url(args, view)
        if code != 0:
            return code

    entry = store.issue_enrollment_code(ttl=args.ttl)
    print(f"pairing code : {entry.code}")
    print(f"valid for    : {args.ttl:.0f}s")
    print(f"trust store  : {store.path}")

    if view is not None and view.self_peer is not None and view.self_peer.addresses:
        print(f"addresses    : {', '.join(view.self_peer.addresses)}")
    print()
    print("On the phone, enter this code once to register its public key.")

    if args.qr and qr_url is not None:
        payload = build_pairing_payload(qr_url, entry.code)
        print()
        print("scan this QR, or open the URI below:")
        _print_qr(render_qr_ascii(payload))
        print(f"pairing uri  : {payload}")
    return 0


def _cmd_devices(args: argparse.Namespace) -> int:
    """List enrolled devices, and grant or revoke access.

    Granting and revoking are host-side acts, one per invocation — the same as
    ``--revoke``. There is no HTTP grant endpoint: an authenticated device
    granting itself permissions would be escalation, and widening access is a
    decision a person makes at this machine.
    """
    from .api.auth import DeviceStore

    store = DeviceStore(args.devices)
    if args.revoke:
        if store.revoke(args.revoke):
            print(f"revoked {args.revoke}")
        else:
            print(f"no such device: {args.revoke}", file=sys.stderr)
            return 1
        return 0

    if args.recovery:
        code = store.issue_recovery_code(args.recovery)
        if code is None:
            print(f"no such device: {args.recovery}", file=sys.stderr)
            return 1
        print(f"recovery code : {code}")
        print()
        print("Shown once. Store it safely: re-pairing with it rotates it, and a")
        print("revoked device cannot use it. The old code stops working now.")
        return 0

    if args.grant or args.revoke_permission:
        device_id = args.grant or args.revoke_permission
        permissions = args.permission or []
        if not permissions:
            print("--permission is required with --grant / --revoke-permission", file=sys.stderr)
            return 2
        for permission in permissions:
            try:
                changed = (
                    store.grant(device_id, permission)
                    if args.grant
                    else store.revoke_permission(device_id, permission)
                )
            except ValueError as exc:
                print(f"refused: {exc}", file=sys.stderr)
                return 2
            if not changed:
                print(f"no such device: {device_id}", file=sys.stderr)
                return 1
        verb = "granted" if args.grant else "revoked"
        print(f"{verb} {', '.join(permissions)} on {device_id}")
        return 0

    devices = store.list()
    if not devices:
        print("no devices enrolled")
        return 0
    for device in devices:
        flags = []
        if device.revoked:
            flags.append("REVOKED")
        if device.fcm_token:
            flags.append("fcm")
        print(
            f"{device.device_id}  {device.curve:<8}  "
            f"{(device.label or '-'):<18}  {','.join(device.permissions) or '-':<24}  "
            f"{','.join(flags) or '-'}"
        )
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    """Run the watcher and the HTTP control plane together.

    Binds loopback by default. Reachability from a phone is the tunnel's job,
    which keeps "what is exposed" answerable from one setting.
    """
    import uvicorn

    from .api.app import ApiConfig, AppContext, create_app
    from .api.auth import DeviceStore, RequestVerifier
    from .api.ratelimit import RateLimiter, StreamRegistry
    from .notify.policy import PushPolicy

    store = Store()
    devices = DeviceStore(args.devices)
    # The sender reads the trust store at send time, so a registration the HTTP
    # plane wrote is visible to the push path without a second registry.
    phone_tokens = StoreBackedRegistry(devices)
    subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    async def on_changes(changes: list[AgentChange]) -> None:
        """Bridge watcher changes to both the policy and the SSE subscribers.

        The push path and the live path are deliberately separate: a phone with
        the app open gets an SSE frame immediately, while a phone with the app
        closed gets FCM, and neither depends on the other being healthy.
        """
        policy: PushPolicy = app.state.policy
        sender = app.state.sender
        state = store.state
        for change in changes:
            decision = policy.decide(change)
            if decision.allowed:
                record = state.agents.get(change.pane_id)
                if record is not None:
                    from .notify.fcm import build_notification

                    notification = build_notification(
                        change,
                        project=state.workspace_label(change.workspace_id),
                        agent_name=record.display_name,
                        title=record.task_title,
                    )
                    with contextlib.suppress(Exception):
                        sender.send(notification)
            for queue in list(subscribers):
                if queue.full():
                    with contextlib.suppress(asyncio.QueueEmpty):
                        queue.get_nowait()
                with contextlib.suppress(asyncio.QueueFull):
                    queue.put_nowait(
                        {
                            "event": "change",
                            "revision": state.revision,
                            "pane_id": change.pane_id,
                            "status": change.after,
                            "decision": str(decision.verdict),
                            "state": state.view(),
                        }
                    )

    watcher = Watcher(
        session=args.session,
        store=store,
        on_changes=on_changes,
        request_timeout=args.timeout,
    )
    context = AppContext(
        store=store,
        devices=devices,
        verifier=RequestVerifier(devices),
        limiter=RateLimiter(),
        streams=StreamRegistry(),
        client=watcher.client,
        watcher=watcher,
        subscribers=subscribers,
    )
    app = create_app(
        context,
        ApiConfig(
            device_store_path=args.devices,
            image_store_dir=args.images,
        ),
    )
    app.state.policy = PushPolicy(quiet_hours=_parse_quiet_hours(args.quiet_hours))
    app.state.sender = _build_sender(phone_tokens)

    async def main() -> None:
        watch_task = asyncio.create_task(watcher.start())
        try:
            await asyncio.wait_for(watcher.booted.wait(), args.boot_timeout)
        except TimeoutError:
            log.error("herdr did not answer within %.0fs", args.boot_timeout)
            watch_task.cancel()
            raise SystemExit(1) from None

        try:
            hosts = parse_bind_hosts(args.host)
            sockets = bind_sockets(hosts, args.port)
        except (ValueError, OSError) as exc:
            log.error("cannot bind %s: %s", args.host, exc)
            watch_task.cancel()
            raise SystemExit(2) from None

        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host=hosts[0],
                port=args.port,
                log_level="warning",
                # No proxy headers: the tunnel terminates TLS in front, and
                # trusting forwarded headers from a loopback listener would let a
                # caller claim any source address.
                proxy_headers=False,
            )
        )
        for host in hosts:
            print(f"gateway on http://{host}:{args.port}")
        print(f"  devices enrolled : {len(devices)}")
        print(f"  herdr            : {store.state.version} ({len(store.state.agents)} agents)")
        try:
            await server.serve(sockets=sockets)
        finally:
            await watcher.stop()
            watch_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watch_task

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        return 130
    return 0


_WILDCARD_HOSTS = frozenset({"", "0.0.0.0", "::", "*"})  # noqa: S104 - the deny-list itself


def parse_bind_hosts(raw: str) -> list[str]:
    """Split ``--host`` into explicit addresses; a wildcard is refused.

    The gateway can send keys to agents, which is control of this machine, so it
    binds only to addresses named on purpose: loopback and, for a phone, the
    Tailscale address. ``0.0.0.0`` or ``::`` would expose it on every interface.
    """
    hosts = [part.strip() for part in raw.split(",")]
    if not hosts or any(host in _WILDCARD_HOSTS for host in hosts):
        raise ValueError("a wildcard bind address is not allowed; name each address")
    return list(dict.fromkeys(hosts))


def bind_sockets(hosts: list[str], port: int) -> list[socket.socket]:
    """Open one listening socket per host so a single server serves them all."""
    sockets: list[socket.socket] = []
    try:
        for host in hosts:
            family = socket.AF_INET6 if ":" in host else socket.AF_INET
            sock = socket.socket(family, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
            sock.listen(128)
            sock.setblocking(False)
            sockets.append(sock)
    except OSError:
        for sock in sockets:
            sock.close()
        raise
    return sockets


def _parse_quiet_hours(raw: str | None) -> tuple[int, int] | None:
    if not raw:
        return None
    try:
        start_text, end_text = raw.split("-", 1)
        start, end = int(start_text), int(end_text)
    except ValueError as exc:
        raise SystemExit("--quiet-hours must look like 23-7") from exc
    if not (0 <= start < 24 and 0 <= end < 24):
        raise SystemExit("--quiet-hours hours must be 0-23")
    return start, end


def _cmd_push_credentials(args: argparse.Namespace) -> int:
    """Move the FCM refresh token out of a plaintext file and into DPAPI.

    Three verbs, deliberately separate, because each is a different amount of
    commitment:

    ``--migrate``  copy the gcloud ADC file into the Credential Manager and
                   delete the source. This is the one you run once.
    ``--status``   report what is stored, without printing anything secret.
    ``--delete``   remove it. Push stops working; the app keeps working on the
                   live stream.

    The deletion is not bundled into the migration as an implicit step even
    though the migration does it, because being able to undo a credential
    operation matters more than being tidy about it.
    """
    from .notify import dpapi

    if args.delete:
        removed = dpapi.delete_credential()
        print("removed" if removed else "nothing was stored")
        return 0

    if args.status:
        token = dpapi.load_refresh_token()
        if token is None:
            print("nothing stored in the Windows Credential Manager")
        else:
            print(f"stored: {dpapi.CREDENTIAL_TARGET}")
            print(f"fields : {', '.join(sorted(token))}")
            print("no plaintext credential file is used")
        print(f"ADC file present: {dpapi.ADC_PATH.is_file()}")
        return 0

    try:
        dpapi.migrate_from_adc()
    except dpapi.CredentialStoreError as exc:
        print(f"could not migrate: {exc}", file=sys.stderr)
        return 1
    print(f"stored in the Windows Credential Manager as {dpapi.CREDENTIAL_TARGET}")
    print(f"removed the plaintext file at {dpapi.ADC_PATH}")
    return 0


def _build_sender(registry: Any) -> Any:
    """Build the push sender, preferring a credential that is not on disk.

    Order is Google's own for a local workstation: user credentials first, a
    service account key only as a last resort. The Credential Manager holds the
    refresh token DPAPI-encrypted, so the plaintext form exists only in this
    process; ``FcmSender`` falls back to ADC, and then to a key file, when
    nothing is stored.

    Failures here are logged and swallowed rather than raised. Push is an
    accelerant — the app works on the live stream without it — and a gateway that
    refuses to start because a credential is missing is worse than one that
    starts and does not push.
    """
    from .notify.fcm import FcmSender

    try:
        from .notify import dpapi

        refresh_token = dpapi.load_refresh_token()
        if refresh_token is not None:
            log.info("push credential: Windows Credential Manager (DPAPI)")
            return FcmSender(registry, refresh_token=refresh_token)
        log.info("push credential: none stored in the Credential Manager")
    except Exception as exc:
        log.warning("could not read the push credential: %s", exc)

    return FcmSender(registry)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="herdr-notify",
        description="Mirror a herdr session to push notifications and a control plane.",
    )
    parser.add_argument("-v", "--verbose", action="count", default=0)
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="check endpoint resolution and optionally ping herdr")
    doctor.add_argument("--session", help="herdr session name (default: the default session)")
    doctor.add_argument("--ping", action="store_true", help="actually connect and send ping")
    doctor.set_defaults(func=_cmd_doctor)

    dump = sub.add_parser("dump", help="print the reduced session state")
    dump.add_argument("--session", help="herdr session name")
    dump.add_argument("--json", action="store_true", help="emit the raw read model")
    dump.add_argument("--follow", "-f", action="store_true", help="keep watching for changes")
    dump.add_argument("--interval", type=float, default=1.0, help="seconds between renders")
    dump.add_argument("--timeout", type=float, default=5.0, help="per-request timeout")
    dump.add_argument(
        "--boot-timeout", type=float, default=15.0, help="seconds to wait for the first snapshot"
    )
    dump.set_defaults(func=_cmd_dump)

    schema = sub.add_parser("schema", help="print the subscription set for given panes")
    schema.add_argument("--pane", action="append", help="pane id (repeatable)")
    schema.set_defaults(func=_cmd_schema)

    default_store = Path.home() / ".config" / "herdr-notify" / "devices.json"

    status = sub.add_parser(
        "status", help="report the endpoint, trust store, gateway and log state"
    )
    status.add_argument("--devices", type=Path, default=default_store, help="trust store path")
    status.add_argument("--port", type=int, default=8787, help="gateway port to probe")
    status.add_argument("--session", help="herdr session name")
    status.set_defaults(func=_cmd_status)

    from .api.auth import SUPPORTED_PERMISSIONS

    permission_choices = sorted(SUPPORTED_PERMISSIONS)

    add = sub.add_parser("add-device", help="register a phone by its public key")
    add.add_argument("--devices", type=Path, default=default_store, help="trust store path")
    add.add_argument("--public-key", required=True, help="base64 public key from the phone")
    add.add_argument("--curve", default="p256", choices=["p256", "ed25519"])
    add.add_argument("--label", help="human name, e.g. 'Pixel 9'")
    add.add_argument("--fcm-token", help="FCM registration token, if already known")
    add.add_argument("--device-id", help="explicit id, for re-adding a known phone")
    add.add_argument(
        "--permission",
        action="append",
        metavar="PERMISSION",
        choices=permission_choices,
        help="grant an explicit permission (repeatable); READ_STATE is the pairing default",
    )
    add.set_defaults(func=_cmd_add_device)

    enroll = sub.add_parser(
        "enroll",
        help="mint a single-use pairing code (for a phone that cannot call a CLI)",
    )
    enroll.add_argument("--devices", type=Path, default=default_store, help="trust store path")
    enroll.add_argument("--ttl", type=float, default=600.0, help="code lifetime in seconds")
    enroll.add_argument(
        "--url",
        help="gateway public base URL for --qr, e.g. https://pc.tailnet.ts.net",
    )
    enroll.add_argument(
        "--qr",
        action="store_true",
        help="also print a scannable QR of the pairing payload (needs a base URL)",
    )
    enroll.set_defaults(func=_cmd_enroll)

    devices = sub.add_parser("devices", help="list enrolled devices, and grant or revoke access")
    devices.add_argument("--devices", type=Path, default=default_store, help="trust store path")
    devices.add_argument("--revoke", metavar="DEVICE_ID", help="revoke this device")
    devices.add_argument(
        "--recovery",
        metavar="DEVICE_ID",
        help="mint a new recovery code for this device (shown once, rotates)",
    )
    devices.add_argument("--grant", metavar="DEVICE_ID", help="grant permissions to this device")
    devices.add_argument(
        "--revoke-permission", metavar="DEVICE_ID", help="remove permissions from this device"
    )
    devices.add_argument(
        "--permission",
        action="append",
        metavar="PERMISSION",
        choices=permission_choices,
        help="a permission to grant or remove (repeatable)",
    )
    devices.set_defaults(func=_cmd_devices)

    creds = sub.add_parser(
        "push-credentials",
        help="manage the FCM credential in the Windows Credential Manager",
    )
    group = creds.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--migrate",
        action="store_true",
        help="move the gcloud ADC file into the Credential Manager and delete it",
    )
    group.add_argument("--status", action="store_true", help="report what is stored")
    group.add_argument("--delete", action="store_true", help="remove the stored credential")
    creds.set_defaults(func=_cmd_push_credentials)

    serve = sub.add_parser("serve", help="run the watcher and the control plane")
    serve.add_argument("--session", help="herdr session name")
    serve.add_argument(
        "--host", default="127.0.0.1", help="comma-separated addresses; never a wildcard"
    )
    serve.add_argument("--port", type=int, default=8787)
    serve.add_argument("--timeout", type=float, default=10.0, help="herdr request timeout")
    serve.add_argument("--boot-timeout", type=float, default=30.0)
    serve.add_argument("--devices", type=Path, default=default_store, help="trust store path")
    serve.add_argument(
        "--images",
        type=Path,
        default=Path.home() / ".config" / "herdr-notify" / "images",
        help="directory where attached images are stored",
    )
    serve.add_argument(
        "--quiet-hours", metavar="START-END", help="local hours to defer review pushes, e.g. 23-7"
    )
    serve.add_argument(
        "--disable-enrollment",
        action="store_true",
        help="refuse new devices; use once the phone is paired",
    )
    serve.set_defaults(func=_cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _configure_logging(args.verbose)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
