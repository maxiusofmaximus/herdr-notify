"""Per-device rate limiting.

Signature verification already stops an unauthenticated caller, so this is not
about preventing brute force. It is about a *legitimate but malfunctioning*
client: a phone on a failing network that retries in a tight loop would otherwise
turn a bug into a self-inflicted denial of service against the gateway, and
through it against the coding agents the gateway drives.

Reads and writes are limited separately. A dashboard that polls state every
second is legitimate; sending three hundred prompts a minute is not, and it
should hit a wall regardless of how well signed the requests are.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Final

#: A dashboard refreshing a few times a minute, with headroom for a reconnect
#: storm after the phone wakes.
READ_PER_MINUTE: Final = 120
WRITE_PER_MINUTE: Final = 30

#: Concurrent long-lived streams per device. SSE holds a worker and a herdr
#: event subscription, so an unbounded number is a resource-exhaustion lever.
MAX_STREAMS_PER_DEVICE: Final = 3

#: Devices tracked before the oldest is forgotten. A signed request can only
#: come from a known device, so this is a memory bound rather than a security
#: control, but it must not grow either.
MAX_TRACKED_DEVICES: Final = 64


@dataclass(slots=True)
class _Bucket:
    window_started: float
    used: int


class RateLimiter:
    """Fixed-window counters, per device, per class."""

    def __init__(
        self,
        *,
        read_per_minute: int = READ_PER_MINUTE,
        write_per_minute: int = WRITE_PER_MINUTE,
        max_devices: int = MAX_TRACKED_DEVICES,
        clock: Any = time.time,
    ) -> None:
        self._read = read_per_minute
        self._write = write_per_minute
        self._max_devices = max_devices
        self._clock = clock
        self._buckets: OrderedDict[tuple[str, str], _Bucket] = OrderedDict()

    def allow(self, device_id: str, *, write: bool) -> tuple[bool, float]:
        """Consume one unit. Returns (allowed, retry_after_seconds)."""
        key = (device_id, "write" if write else "read")
        now = float(self._clock())
        bucket = self._buckets.get(key)
        if bucket is None or now - bucket.window_started >= 60.0:
            bucket = _Bucket(window_started=now, used=0)
            self._buckets[key] = bucket
        self._buckets.move_to_end(key)

        limit = self._write if write else self._read
        if bucket.used >= limit:
            retry_after = max(0.0, 60.0 - (now - bucket.window_started))
            return False, retry_after
        bucket.used += 1
        self._evict(now)
        return True, 0.0

    def _evict(self, now: float) -> None:
        stale = [k for k, b in self._buckets.items() if now - b.window_started >= 120.0]
        for key in stale:
            self._buckets.pop(key, None)
        while len(self._buckets) > self._max_devices * 2:
            self._buckets.popitem(last=False)

    def reset(self, device_id: str | None = None) -> None:
        if device_id is None:
            self._buckets.clear()
            return
        for key in [k for k in self._buckets if k[0] == device_id]:
            self._buckets.pop(key, None)

    def used(self, device_id: str) -> dict[str, int]:
        return {
            kind: bucket.used
            for (device, kind), bucket in self._buckets.items()
            if device == device_id
        }


class StreamRegistry:
    """Counts open event streams per device."""

    def __init__(self, *, per_device: int = MAX_STREAMS_PER_DEVICE) -> None:
        self._per_device = per_device
        self._open: dict[str, int] = {}

    def acquire(self, device_id: str) -> bool:
        current = self._open.get(device_id, 0)
        if current >= self._per_device:
            return False
        self._open[device_id] = current + 1
        return True

    def release(self, device_id: str) -> None:
        remaining = self._open.get(device_id, 1) - 1
        if remaining <= 0:
            self._open.pop(device_id, None)
        else:
            self._open[device_id] = remaining

    def open_for(self, device_id: str) -> int:
        return self._open.get(device_id, 0)

    @property
    def total(self) -> int:
        return sum(self._open.values())


__all__ = [
    "MAX_STREAMS_PER_DEVICE",
    "READ_PER_MINUTE",
    "WRITE_PER_MINUTE",
    "RateLimiter",
    "StreamRegistry",
]
