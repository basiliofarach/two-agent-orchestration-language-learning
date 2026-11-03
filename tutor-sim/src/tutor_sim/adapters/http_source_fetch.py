"""Fetch a pinned source over HTTPS, or from the cache alone."""

from pathlib import Path
from urllib.parse import urlsplit

import httpx

from tutor_sim.adapters.digest import ArtefactDigest
from tutor_sim.domain.models.source import SourceRecord
from tutor_sim.domain.ports.source_fetch import SourceFetchPort

_MAX_REDIRECTS = 5


class CacheMiss(FileNotFoundError):
    """The offline fetch has no cached artefact."""


class UnsafeSourceUrl(ValueError):
    """The URL is not HTTPS, or its host is not on the catalogue allowlist."""


class HttpSourceFetch(SourceFetchPort):
    """Download one pinned URL and keep the bytes in the cache."""

    def __init__(
        self,
        client: httpx.Client,
        cache: Path,
        digest: ArtefactDigest,
        allowed_hosts: frozenset[str],
    ) -> None:
        self._client = client
        self._cache = cache
        self._digest = digest
        self._allowed_hosts = allowed_hosts

    def fetch(self, source: SourceRecord) -> bytes:
        """Return the body when its digest matches. A mismatch is fatal.

        Redirects are followed here, one hop at a time, so every hop is
        checked against the allowlist. The client is never left to follow
        them itself, whatever it was configured with.
        """
        self._admit(source.url)
        response = self._client.get(source.url, follow_redirects=False)
        hops = 0
        while response.next_request is not None:
            if hops == _MAX_REDIRECTS:
                msg = f"{source.source_id} exceeds {_MAX_REDIRECTS} redirects"
                raise UnsafeSourceUrl(msg)
            following = response.next_request
            self._admit(str(following.url))
            response = self._client.send(following, follow_redirects=False)
            hops += 1
        response.raise_for_status()
        body = response.content
        self._digest.check(source, body)
        self._cache.mkdir(parents=True, exist_ok=True)
        (self._cache / source.sha256).write_bytes(body)
        return body

    def _admit(self, url: str) -> None:
        parsed = urlsplit(url)
        host = parsed.hostname
        if parsed.scheme != "https" or host not in self._allowed_hosts:
            msg = f"{url} is not on an allowlisted https host"
            raise UnsafeSourceUrl(msg)


class CachedOnlySourceFetch(SourceFetchPort):
    """Read the cache. An offline rebuild does not open a connection."""

    def __init__(self, cache: Path, digest: ArtefactDigest) -> None:
        self._cache = cache
        self._digest = digest

    def fetch(self, source: SourceRecord) -> bytes:
        """Return the cached artefact. A missing or wrong file is fatal."""
        path = self._cache / source.sha256
        if not path.is_file():
            msg = f"{source.source_id} is not in the cache"
            raise CacheMiss(msg)
        body = path.read_bytes()
        self._digest.check(source, body)
        return body
