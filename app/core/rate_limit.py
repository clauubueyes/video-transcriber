"""Límite de frecuencia local por identidad de token."""

from collections import defaultdict, deque
from collections.abc import Callable
from threading import Lock
from time import monotonic


class TokenRateLimiter:
    """Admite hasta un número fijo de trabajos por ventana temporal."""

    def __init__(
        self,
        max_requests: int,
        window_seconds: float,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._clock = clock
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, token_id: str) -> bool:
        """Registra la solicitud cuando queda cuota disponible."""
        now = self._clock()
        with self._lock:
            requests = self._requests[token_id]
            cutoff = now - self._window_seconds
            while requests and requests[0] <= cutoff:
                requests.popleft()
            if len(requests) >= self._max_requests:
                return False
            requests.append(now)
            return True
