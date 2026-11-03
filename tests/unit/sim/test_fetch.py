"""Source fetch, the dataset store, and the catalogue."""

import hashlib
import json
from datetime import date
from pathlib import Path

import httpx
import pytest
from tests.support.repository import RepositoryPaths

from tutor_sim.adapters.digest import ArtefactDigest, DigestMismatch
from tutor_sim.adapters.file_dataset_store import (
    FileDatasetStore,
    NotRedistributable,
    PathEscapesTree,
)
from tutor_sim.adapters.http_source_fetch import (
    CachedOnlySourceFetch,
    CacheMiss,
    HttpSourceFetch,
    UnsafeSourceUrl,
)
from tutor_sim.catalogue import CatalogueDigest, SourceCatalogue, SourceNotAdmitted
from tutor_sim.domain.models.source import SourceRecord
from tutor_sim.domain.models.storage import DatasetWrite
from tutor_sim.domain.ports.dataset_store import DatasetStorePort
from tutor_sim.domain.ports.source_fetch import SourceFetchPort

_BODY = b"pinned-artefact"
_DIGEST = hashlib.sha256(_BODY).hexdigest()


class OneSource:
    def record(self, url: str = "https://example.invalid/a") -> SourceRecord:
        return SourceRecord(
            source_id="clear-corpus",
            title="CLEAR",
            url=url,
            revision="2026-11-03",
            sha256=_DIGEST,
            licence="custom:public-domain-excerpts",
            licence_url="https://example.invalid/licence",
            redistributable=True,
            use="kb",
            attribution="Crossley et al. 2023",
        )


class ScriptedFetch:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self._body = body
        self._status = status

    def client(self) -> httpx.Client:
        body = self._body
        status = self._status

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(status, content=body)

        return httpx.Client(transport=httpx.MockTransport(handler))


class Redirects:
    """Answer 302 for each mapped URL and 200 with the body otherwise."""

    def __init__(self, hops: dict[str, str]) -> None:
        self._hops = hops

    def client(self, follow: bool = False) -> httpx.Client:
        hops = self._hops

        def handler(request: httpx.Request) -> httpx.Response:
            target = hops.get(str(request.url))
            if target is not None:
                return httpx.Response(302, headers={"Location": target})
            return httpx.Response(200, content=_BODY)

        return httpx.Client(
            transport=httpx.MockTransport(handler), follow_redirects=follow
        )


class TestDigest:
    def test_a_matching_body_is_accepted(self) -> None:
        ArtefactDigest().check(OneSource().record(), _BODY)

    def test_a_mismatch_is_fatal(self) -> None:
        with pytest.raises(DigestMismatch, match="clear-corpus"):
            ArtefactDigest().check(OneSource().record(), b"other")


class TestHttpSourceFetch:
    def test_a_matching_download_is_cached(self, tmp_path: Path) -> None:
        cache = tmp_path / "cache"
        fetch = HttpSourceFetch(
            ScriptedFetch(_BODY).client(),
            cache,
            ArtefactDigest(),
            frozenset({"example.invalid"}),
        )
        assert fetch.fetch(OneSource().record()) == _BODY
        assert (cache / _DIGEST).read_bytes() == _BODY

    def test_a_digest_mismatch_is_fatal(self, tmp_path: Path) -> None:
        fetch = HttpSourceFetch(
            ScriptedFetch(b"other").client(),
            tmp_path,
            ArtefactDigest(),
            frozenset({"example.invalid"}),
        )
        with pytest.raises(DigestMismatch):
            fetch.fetch(OneSource().record())

    def test_an_http_error_is_fatal(self, tmp_path: Path) -> None:
        fetch = HttpSourceFetch(
            ScriptedFetch(_BODY, status=404).client(),
            tmp_path,
            ArtefactDigest(),
            frozenset({"example.invalid"}),
        )
        with pytest.raises(httpx.HTTPStatusError):
            fetch.fetch(OneSource().record())

    def test_http_is_refused(self, tmp_path: Path) -> None:
        fetch = HttpSourceFetch(
            ScriptedFetch(_BODY).client(),
            tmp_path,
            ArtefactDigest(),
            frozenset({"example.invalid"}),
        )
        with pytest.raises(UnsafeSourceUrl):
            fetch.fetch(OneSource().record("http://example.invalid/a"))

    def test_a_host_outside_the_allowlist_is_refused(self, tmp_path: Path) -> None:
        fetch = HttpSourceFetch(
            ScriptedFetch(_BODY).client(),
            tmp_path,
            ArtefactDigest(),
            frozenset({"example.invalid"}),
        )
        with pytest.raises(UnsafeSourceUrl):
            fetch.fetch(OneSource().record("https://evil.example/a"))

    def test_an_allowlisted_redirect_is_followed(self, tmp_path: Path) -> None:
        fetch = HttpSourceFetch(
            Redirects(
                {"https://example.invalid/a": "https://cdn.example.invalid/b"}
            ).client(),
            tmp_path,
            ArtefactDigest(),
            frozenset({"example.invalid", "cdn.example.invalid"}),
        )
        assert fetch.fetch(OneSource().record()) == _BODY

    def test_a_client_that_follows_redirects_itself_is_still_checked(
        self, tmp_path: Path
    ) -> None:
        fetch = HttpSourceFetch(
            Redirects({"https://example.invalid/a": "https://evil.example/b"}).client(
                follow=True
            ),
            tmp_path,
            ArtefactDigest(),
            frozenset({"example.invalid"}),
        )
        with pytest.raises(UnsafeSourceUrl, match="evil.example"):
            fetch.fetch(OneSource().record())

    @pytest.mark.parametrize(
        "target",
        ["https://evil.example/b", "http://example.invalid/b"],
    )
    def test_a_redirect_off_the_allowlist_is_refused(
        self, tmp_path: Path, target: str
    ) -> None:
        fetch = HttpSourceFetch(
            Redirects({"https://example.invalid/a": target}).client(),
            tmp_path,
            ArtefactDigest(),
            frozenset({"example.invalid"}),
        )
        with pytest.raises(UnsafeSourceUrl):
            fetch.fetch(OneSource().record())

    def test_a_redirect_loop_is_refused(self, tmp_path: Path) -> None:
        fetch = HttpSourceFetch(
            Redirects(
                {
                    "https://example.invalid/a": "https://example.invalid/b",
                    "https://example.invalid/b": "https://example.invalid/a",
                }
            ).client(),
            tmp_path,
            ArtefactDigest(),
            frozenset({"example.invalid"}),
        )
        with pytest.raises(UnsafeSourceUrl, match="redirects"):
            fetch.fetch(OneSource().record())

    def test_a_port_without_fetch_cannot_be_instantiated(self) -> None:
        incomplete = type("Incomplete", (SourceFetchPort,), {})
        with pytest.raises(TypeError, match="abstract"):
            incomplete()


class TestCachedOnlySourceFetch:
    def test_the_cache_is_returned_when_the_digest_matches(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / _DIGEST).write_bytes(_BODY)
        fetch = CachedOnlySourceFetch(tmp_path, ArtefactDigest())
        assert fetch.fetch(OneSource().record()) == _BODY

    def test_a_missing_file_is_fatal(self, tmp_path: Path) -> None:
        fetch = CachedOnlySourceFetch(tmp_path, ArtefactDigest())
        with pytest.raises(CacheMiss, match="clear-corpus"):
            fetch.fetch(OneSource().record())

    def test_a_cached_mismatch_is_fatal(self, tmp_path: Path) -> None:
        (tmp_path / _DIGEST).write_bytes(b"other")
        fetch = CachedOnlySourceFetch(tmp_path, ArtefactDigest())
        with pytest.raises(DigestMismatch):
            fetch.fetch(OneSource().record())


class TestFileDatasetStore:
    def test_a_redistributable_file_lands_in_public(self, tmp_path: Path) -> None:
        FileDatasetStore(tmp_path).write(
            DatasetWrite(
                relative_path="kb/notes.txt",
                body=b"hola",
                redistributable=True,
                tree="public",
            )
        )
        assert (tmp_path / "public" / "kb" / "notes.txt").read_bytes() == b"hola"

    def test_a_restricted_file_lands_in_restricted(self, tmp_path: Path) -> None:
        FileDatasetStore(tmp_path).write(
            DatasetWrite(
                relative_path="payloads/harm.txt",
                body=b"held",
                redistributable=False,
                tree="restricted",
            )
        )
        assert (tmp_path / "restricted" / "payloads" / "harm.txt").read_bytes() == (
            b"held"
        )

    def test_a_non_redistributable_file_cannot_enter_public(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(NotRedistributable, match="not redistributable"):
            FileDatasetStore(tmp_path).write(
                DatasetWrite(
                    relative_path="fce.txt",
                    body=b"secret",
                    redistributable=False,
                    tree="public",
                )
            )
        assert not (tmp_path / "public" / "fce.txt").exists()

    def test_a_path_that_leaves_the_tree_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(PathEscapesTree):
            FileDatasetStore(tmp_path).write(
                DatasetWrite(
                    relative_path="../outside.txt",
                    body=b"x",
                    redistributable=True,
                    tree="public",
                )
            )

    def test_the_tree_directory_itself_is_not_an_escape(self, tmp_path: Path) -> None:
        (tmp_path / "public").mkdir()
        with pytest.raises(IsADirectoryError):
            FileDatasetStore(tmp_path).write(
                DatasetWrite(
                    relative_path=".",
                    body=b"x",
                    redistributable=True,
                    tree="public",
                )
            )

    def test_a_port_without_write_cannot_be_instantiated(self) -> None:
        incomplete = type("Incomplete", (DatasetStorePort,), {})
        with pytest.raises(TypeError, match="abstract"):
            incomplete()


class TestSourceCatalogue:
    def test_the_committed_catalogue_matches_its_pin_files(self) -> None:
        root = RepositoryPaths().root() / "datasets" / "sim" / "unreleased" / "public"
        records = SourceCatalogue(root / "sources.json").load()
        digest = CatalogueDigest()
        excluded = {
            "write-and-improve-2024",
            "efcamdat",
            "ai4privacy",
            "english-vocabulary-profile",
            "clear-corpus",
            "standard-ebooks",
            "project-gutenberg",
            "simple-english-wikipedia",
            "onestopenglish",
            "author-grammar-notes",
        }
        present = {record.source_id for record in records}
        assert {
            "cefr-sp-wiki-auto",
            "cefr-sp-score",
            "cefr-j-grammar-profile",
            "treetagger",
        } <= present
        assert present.isdisjoint(excluded)
        for record in records:
            pin = root / "pins" / f"{record.source_id}.json"
            body = json.loads(pin.read_text(encoding="utf-8"))
            assert body["digest_scope"] == "pin-file"
            assert "not of a fetched artefact" in body["note"]
            assert record.sha256 == digest.of_file(pin)
            assert record.licence_review == "pending"
            assert record.source_id not in excluded
            assert record.revision != "latest"

    def test_an_excluded_source_is_not_admitted(self, tmp_path: Path) -> None:
        path = self._write(tmp_path, source_id="efcamdat")
        with pytest.raises(SourceNotAdmitted, match="efcamdat"):
            SourceCatalogue(path).load()

    def test_a_rejected_review_is_not_admitted(self, tmp_path: Path) -> None:
        path = self._write(
            tmp_path,
            licence_review="rejected",
            reviewed_by="author",
            reviewed_on="2026-11-03",
            review_note="The terms forbid this use.",
        )
        with pytest.raises(SourceNotAdmitted, match="clear-corpus"):
            SourceCatalogue(path).load()

    def _write(self, tmp_path: Path, **updates: object) -> Path:
        payload = OneSource().record().model_dump(mode="json")
        payload.update(updates)
        if "reviewed_on" in updates and updates["reviewed_on"] == "2026-11-03":
            payload["reviewed_on"] = date(2026, 11, 3).isoformat()
        path = tmp_path / "sources.json"
        path.write_text(json.dumps([payload]), encoding="utf-8")
        return path
