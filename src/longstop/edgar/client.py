"""Rate-limited, cached HTTP access to EDGAR.

The SEC asks automated clients to identify themselves by email and to stay
under ten requests a second. Both are enforced here rather than left to the
caller to remember, because a crawler that forgets gets the whole address
blocked and the block is not obvious from the response body.

Nothing is hardcoded. The contact address comes from LONGSTOP_CONTACT and the
client refuses to make a request without one.
"""
from __future__ import annotations

import gzip
import hashlib
import http.client
import random
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

CONTACT_ENV = "LONGSTOP_CONTACT"
REQUESTS_PER_SECOND = 6.0
MAX_RETRIES = 8
BACKOFF_BASE_SECONDS = 1.7
BACKOFF_CAP_SECONDS = 45.0

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CACHE = REPO_ROOT / "data" / "cache"


class ContactNotSet(RuntimeError):
    """Raised when LONGSTOP_CONTACT is missing or does not look like an email."""


class FetchError(RuntimeError):
    """Raised when a URL could not be fetched after the retry budget."""


def backoff_seconds(attempt: int) -> float:
    """Exponential, capped, with jitter.

    Jitter matters when a transient DNS failure hits a long crawl: without it
    every retry lands on the same schedule and the whole budget can be spent
    inside one outage.
    """
    base = min(BACKOFF_CAP_SECONDS, BACKOFF_BASE_SECONDS ** (attempt + 1))
    return base * (0.5 + random.random())


def user_agent() -> str:
    contact = os.environ.get(CONTACT_ENV, "").strip()
    if "@" not in contact or contact.startswith("@") or contact.endswith("@"):
        raise ContactNotSet(
            f"Set {CONTACT_ENV} to a real email address before fetching from EDGAR.\n"
            f"  export {CONTACT_ENV}='you@example.com'\n"
            "The SEC requires automated clients to identify themselves and blocks "
            "those that do not."
        )
    return f"Longstop research client {contact}"


class RateLimiter:
    """Spaces requests by wall clock. Shared across threads."""

    def __init__(self, per_second: float = REQUESTS_PER_SECOND) -> None:
        self._min_interval = 1.0 / per_second
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            gap = now - self._last
            if gap < self._min_interval:
                time.sleep(self._min_interval - gap)
            self._last = time.monotonic()


class EdgarClient:
    """Fetches EDGAR URLs, caching every response on disk.

    The cache is what makes a rebuild free and a benchmark reproducible. It is
    keyed by URL, never expires, and is gitignored.
    """

    def __init__(self, cache_dir: Path | None = None, per_second: float = REQUESTS_PER_SECOND) -> None:
        self.cache_dir = Path(cache_dir) if cache_dir else DEFAULT_CACHE
        self.limiter = RateLimiter(per_second)
        self.stats = {"hits": 0, "misses": 0, "retries": 0}

    def cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode()).hexdigest()
        return self.cache_dir / digest[:2] / f"{digest}.bin"

    def get(self, url: str, *, allow_404: bool = False, store: bool = True) -> bytes | None:
        """store=False fetches without persisting the body.

        The quarterly form indexes are fifty megabytes each and are thrown away
        after filtering, so caching them would cost several gigabytes to hold
        data that is never read twice. The filtered rows are cached instead.
        """
        path = self.cache_path(url)
        if store and path.exists():
            self.stats["hits"] += 1
            return path.read_bytes()

        body = self._fetch(url, allow_404=allow_404)
        if body is None:
            return None
        if not store:
            self.stats["misses"] += 1
            return body
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(body)
        tmp.replace(path)
        self.stats["misses"] += 1
        return body

    def _fetch(self, url: str, *, allow_404: bool) -> bytes | None:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": user_agent(),
                "Accept-Encoding": "gzip, deflate",
            },
        )
        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES):
            self.limiter.wait()
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    raw = response.read()
                    if response.headers.get("Content-Encoding") == "gzip":
                        raw = gzip.decompress(raw)
                    return raw
            except urllib.error.HTTPError as exc:
                if exc.code == 404 and allow_404:
                    return None
                if exc.code in (403, 429, 503):
                    last_error = exc
                    self.stats["retries"] += 1
                    time.sleep(backoff_seconds(attempt))
                    continue
                raise FetchError(f"{exc.code} for {url}") from exc
            except (
                urllib.error.URLError,
                TimeoutError,
                ConnectionError,
                # A fifty megabyte chunked response truncated mid-read raises
                # IncompleteRead, which is an HTTPException and not a URLError.
                # Leaving it out of this tuple killed a ninety-six quarter crawl
                # at quarter fifty-two.
                http.client.HTTPException,
            ) as exc:
                last_error = exc
                self.stats["retries"] += 1
                time.sleep(backoff_seconds(attempt))
        raise FetchError(f"gave up on {url} after {MAX_RETRIES} attempts: {last_error}")
