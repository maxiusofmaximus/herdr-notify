"""herdr's local IPC endpoint as a stream that can always be closed.

Why this exists
---------------
Windows named pipes have no read timeout, and a blocking ``ReadFile`` on one
cannot be interrupted by closing the handle from another thread: ``CloseHandle``
waits for the pending read, and the pending read waits for data. That deadlock
is not hypothetical — it hung the first working version of this client.

herdr's own client solves it by peeking before reading
(``poll_local_stream_read_count`` in ``src/ipc.rs``): ask how many bytes are
available, and only issue a ``ReadFile`` for a count that is already available.
The read then returns immediately, so the reader is never parked in the kernel
and closing the handle is always safe. This module mirrors that approach, and
gains two things herdr's short-lived CLI client does not need: real read
timeouts, and a close that joins its reader before releasing the handle.

Going through the Win32 API rather than Python's ``open()`` is also what makes
bidirectional use correct. The CRT file object keeps a *single* position shared
by reads and writes, so a read followed by a write is rejected with ``EINVAL``.
``ReadFile``/``WriteFile`` have no shared position.

The POSIX path uses ``select`` for the same reason: never park in ``recv`` when
the peer may be gone, so a close cannot strand the reader thread.
"""

from __future__ import annotations

import contextlib
import errno
import select
import socket
import sys
import threading
from collections.abc import Iterator
from typing import Final

POLL_INTERVAL: Final = 0.005
"""Seconds between availability checks. Low enough to feel instant, high enough
that an idle subscription costs nothing measurable."""

MAX_POLL_WAITS: Final = 4_000
"""Ceiling on consecutive empty polls (~20s) before treating the peer as gone,
so a server that neither answers nor closes cannot pin the reader forever."""


class TransportError(RuntimeError):
    """The endpoint could not be opened or used."""


class TransportClosed(TransportError):
    """The peer closed the endpoint, or we closed it deliberately."""


# -- Windows ---------------------------------------------------------------

if sys.platform == "win32":
    import ctypes
    import ctypes.wintypes as _w

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _GENERIC_READ: Final = 0x8000_0000
    _GENERIC_WRITE: Final = 0x4000_0000
    _OPEN_EXISTING: Final = 3
    _INVALID_HANDLE_VALUE: Final = ctypes.c_void_p(-1).value
    _ERROR_BROKEN_PIPE: Final = 109
    _ERROR_PIPE_NOT_CONNECTED: Final = 233
    _ERROR_OPERATION_ABORTED: Final = 995

    # Without explicit prototypes ctypes defaults every integer argument and
    # return to c_int, which truncates a 64-bit HANDLE to 32 bits. The result is
    # ERROR_INVALID_HANDLE on the first WriteFile — silent, and impossible to
    # diagnose from the error alone.
    _kernel32.CreateFileW.restype = ctypes.c_void_p
    _kernel32.CreateFileW.argtypes = [
        ctypes.c_wchar_p,  # lpFileName
        ctypes.c_uint32,  # dwDesiredAccess
        ctypes.c_uint32,  # dwShareMode
        ctypes.c_void_p,  # lpSecurityAttributes
        ctypes.c_uint32,  # dwCreationDisposition
        ctypes.c_uint32,  # dwFlagsAndAttributes
        ctypes.c_void_p,  # hTemplateFile
    ]
    _kernel32.PeekNamedPipe.restype = ctypes.c_int
    _kernel32.PeekNamedPipe.argtypes = [
        _w.HANDLE,  # hNamedPipe
        ctypes.c_void_p,  # lpBytesRead (unused)
        ctypes.c_uint32,  # nBufferSize (unused)
        ctypes.c_void_p,  # lpTotalBytesRead (unused)
        ctypes.POINTER(_w.DWORD),
        ctypes.c_void_p,  # lpBytesLeftThisMessage (unused)
    ]
    _kernel32.ReadFile.restype = ctypes.c_int
    _kernel32.ReadFile.argtypes = [
        _w.HANDLE,
        ctypes.c_void_p,  # lpBuffer
        _w.DWORD,  # nNumberOfBytesToRead
        ctypes.POINTER(_w.DWORD),
        ctypes.c_void_p,  # lpOverlapped
    ]
    _kernel32.WriteFile.restype = ctypes.c_int
    _kernel32.WriteFile.argtypes = [
        _w.HANDLE,
        ctypes.c_void_p,  # lpBuffer
        _w.DWORD,  # nNumberOfBytesToWrite
        ctypes.POINTER(_w.DWORD),
        ctypes.c_void_p,  # lpOverlapped
    ]
    _kernel32.CloseHandle.restype = ctypes.c_int
    _kernel32.CloseHandle.argtypes = [_w.HANDLE]

    def _open_windows(address: str) -> int:
        handle = _kernel32.CreateFileW(
            address,
            _GENERIC_READ | _GENERIC_WRITE,
            0,  # herdr sets its own DACL; we must not widen it
            None,
            _OPEN_EXISTING,
            0,  # not FILE_FLAG_OVERLAPPED: we poll instead
            None,
        )
        if handle == _INVALID_HANDLE_VALUE:
            code = ctypes.get_last_error()
            raise TransportError(f"cannot open {address} (winerror {code})")
        return int(handle)

    def _peek_windows(handle: int) -> int:
        available = _w.DWORD()
        ok = _kernel32.PeekNamedPipe(
            _w.HANDLE(handle), None, 0, None, ctypes.byref(available), None
        )
        if not ok:
            code = ctypes.get_last_error()
            if code in (_ERROR_BROKEN_PIPE, _ERROR_PIPE_NOT_CONNECTED):
                raise TransportClosed(f"pipe closed by peer (winerror {code})")
            raise TransportError(f"PeekNamedPipe failed (winerror {code})")
        return int(available.value)

    def _read_windows(handle: int, count: int) -> bytes:
        buffer = ctypes.create_string_buffer(count)
        read = _w.DWORD()
        ok = _kernel32.ReadFile(_w.HANDLE(handle), buffer, count, ctypes.byref(read), None)
        if not ok:
            code = ctypes.get_last_error()
            if code in (_ERROR_BROKEN_PIPE, _ERROR_PIPE_NOT_CONNECTED, _ERROR_OPERATION_ABORTED):
                raise TransportClosed(f"pipe read aborted (winerror {code})")
            raise TransportError(f"ReadFile failed (winerror {code})")
        return buffer.raw[: read.value]

    def _write_windows(handle: int, data: bytes) -> None:
        written = _w.DWORD()
        ok = _kernel32.WriteFile(_w.HANDLE(handle), data, len(data), ctypes.byref(written), None)
        if not ok:
            code = ctypes.get_last_error()
            if code in (_ERROR_BROKEN_PIPE, _ERROR_PIPE_NOT_CONNECTED):
                raise TransportClosed(f"pipe closed by peer (winerror {code})")
            raise TransportError(f"WriteFile failed (winerror {code})")
        if written.value != len(data):
            raise TransportError(f"short write: {written.value} of {len(data)} bytes")

    def _close_windows(handle: int) -> None:
        _kernel32.CloseHandle(_w.HANDLE(handle))

    def _pipe_namespace(path: str) -> str:
        return rf"\\.\pipe\{path}"

else:  # pragma: no cover - exercised on POSIX only

    def _open_windows(address: str) -> int:  # type: ignore[misc]
        raise TransportError("the Windows pipe backend is unavailable on this platform")

    def _peek_windows(handle: int) -> int:  # type: ignore[misc]
        raise TransportError("the Windows pipe backend is unavailable on this platform")

    def _read_windows(handle: int, count: int) -> bytes:  # type: ignore[misc]
        raise TransportError("the Windows pipe backend is unavailable on this platform")

    def _write_windows(handle: int, data: bytes) -> None:  # type: ignore[misc]
        raise TransportError("the Windows pipe backend is unavailable on this platform")

    def _close_windows(handle: int) -> None:  # type: ignore[misc]
        raise TransportError("the Windows pipe backend is unavailable on this platform")

    def _pipe_namespace(path: str) -> str:
        return path


class LocalStream:
    """A bidirectional byte stream to herdr that is always closable.

    Takes the endpoint's *filesystem path*, not a transport address: turning it
    into a ``\\\\.\\pipe\\`` name is this layer's job. Not thread-safe for
    concurrent writes; the one writer in this codebase is the subscribe request,
    issued before the reader exists.
    """

    def __init__(self, path: str, *, is_named_pipe: bool) -> None:
        self.path = path
        self.address = _pipe_namespace(path) if is_named_pipe else path
        self.is_named_pipe = is_named_pipe
        self._handle: int | socket.socket | None = None
        self._closed = threading.Event()
        self._buffer = bytearray()

    # -- lifecycle ---------------------------------------------------------

    def open(self) -> None:
        if self._handle is not None:
            # Already connected, which is how an injected test transport arrives.
            return
        if self.is_named_pipe:
            self._handle = _open_windows(self.address)
            return
        # getattr rather than socket.AF_UNIX: type stubs for Windows omit the
        # attribute, POSIX ones include it, and this is the only spelling both
        # accept. The runtime check above is the real guard.
        af_unix = getattr(socket, "AF_UNIX", None)
        if af_unix is None:
            raise TransportError("this Python build has no AF_UNIX support")
        sock = socket.socket(af_unix, socket.SOCK_STREAM)
        try:
            sock.settimeout(5.0)
            sock.connect(self.address)
        except OSError as exc:
            sock.close()
            raise TransportError(f"cannot connect to {self.address}: {exc}") from exc
        sock.settimeout(None)
        self._handle = sock

    @property
    def closed(self) -> bool:
        return self._closed.is_set()

    def close(self) -> None:
        """Release the endpoint. Safe to call from any thread, repeatedly."""
        if self._closed.is_set():
            return
        self._closed.set()
        handle, self._handle = self._handle, None
        if handle is None:
            return
        if self.is_named_pipe:
            with contextlib.suppress(Exception):
                _close_windows(int(handle))  # type: ignore[arg-type]
        else:
            with contextlib.suppress(Exception):
                handle.shutdown(socket.SHUT_RDWR)  # type: ignore[union-attr]
            with contextlib.suppress(Exception):
                handle.close()  # type: ignore[union-attr]

    def __enter__(self) -> LocalStream:
        self.open()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @classmethod
    def from_socket(cls, sock: socket.socket) -> LocalStream:
        """Adopt an already-connected socket.

        The test seam. Production always builds a named pipe or an AF_UNIX
        socket; tests need a platform-independent duplex stream, and a loopback
        TCP pair is the only one available on a Windows host whose Python lacks
        AF_UNIX. Everything above this constructor is identical either way, so
        the tests exercise the real framing and close logic.
        """
        stream = cls("<injected-socket>", is_named_pipe=False)
        stream._handle = sock
        return stream

    # -- io ----------------------------------------------------------------

    def write_line(self, payload: bytes) -> None:
        """Write one newline-terminated frame."""
        if self._closed.is_set() or self._handle is None:
            raise TransportClosed("stream is closed")
        frame = payload.rstrip(b"\n") + b"\n"
        if self.is_named_pipe:
            _write_windows(int(self._handle), frame)  # type: ignore[arg-type]
            return
        try:
            self._handle.sendall(frame)  # type: ignore[union-attr]
        except OSError as exc:
            raise TransportClosed(f"write failed: {exc}") from exc

    def _available(self) -> int:
        """Bytes readable right now, without blocking."""
        assert self._handle is not None
        if self.is_named_pipe:
            return _peek_windows(int(self._handle))  # type: ignore[arg-type]
        sock: socket.socket = self._handle  # type: ignore[assignment]
        try:
            readable, _, _ = select.select([sock], [], [], 0)
        except OSError as exc:
            raise TransportClosed(f"select failed: {exc}") from exc
        if not readable:
            return 0
        return 1 if sock.recv(1, socket.MSG_PEEK) else 0

    def _read(self, count: int) -> bytes:
        assert self._handle is not None
        if self.is_named_pipe:
            return _read_windows(int(self._handle), count)  # type: ignore[arg-type]
        sock: socket.socket = self._handle  # type: ignore[assignment]
        try:
            return sock.recv(count)
        except OSError as exc:
            if exc.errno in (errno.ECONNRESET, errno.EBADF):
                raise TransportClosed(f"recv failed: {exc}") from exc
            raise

    def read_line(self, *, timeout: float | None = None) -> bytes | None:
        """Return the next newline-terminated frame, or None at EOF/timeout.

        Never parks in the kernel: availability is polled first, so a close from
        another thread is observed within one poll interval.
        """
        import time

        deadline = None if timeout is None else time.monotonic() + timeout
        idle_polls = 0

        while True:
            if self._closed.is_set():
                return None
            index = self._buffer.find(b"\n")
            if index >= 0:
                line = bytes(self._buffer[:index])
                del self._buffer[: index + 1]
                return line

            if deadline is not None and time.monotonic() >= deadline:
                return None

            try:
                available = self._available()
            except TransportClosed:
                if self._buffer:
                    line = bytes(self._buffer)
                    self._buffer.clear()
                    return line
                return None

            if available:
                idle_polls = 0
                chunk = self._read(available)
                if not chunk:
                    if self._buffer:
                        line = bytes(self._buffer)
                        self._buffer.clear()
                        return line
                    return None
                self._buffer += chunk
                continue

            idle_polls += 1
            if idle_polls > MAX_POLL_WAITS:
                raise TransportClosed("peer neither answered nor closed within the poll ceiling")
            time.sleep(POLL_INTERVAL)

    def iter_lines(self, *, stop: threading.Event | None = None) -> Iterator[bytes]:
        """Yield frames until EOF, the stream is closed, or ``stop`` is set."""
        while not self._closed.is_set():
            if stop is not None and stop.is_set():
                return
            try:
                line = self.read_line(timeout=POLL_INTERVAL * 4)
            except TransportClosed:
                return
            if line is None:
                continue
            if line.strip():
                yield line


__all__ = [
    "MAX_POLL_WAITS",
    "POLL_INTERVAL",
    "LocalStream",
    "TransportClosed",
    "TransportError",
]
