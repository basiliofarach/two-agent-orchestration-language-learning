"""Revision naming: a UTC stamp orders the file, Alembic's hash is the identity.

The shipped ``alembic.ini`` is the subject. The test copies it, redirects the
script location and points the URL at a closed port, so a revision that reaches
the database fails here rather than silently depending on one.
"""

import configparser
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from alembic import command
from alembic.config import Config

_FILENAME = re.compile(r"^(\d{12})_([0-9a-f]{12})_(\w+)\.py$")
_CLOSED_PORT = "postgresql+psycopg://tutor:tutor@127.0.0.1:1/tutor"


class RevisionTree:
    """A throwaway tree running the shipped configuration and environment."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._source = Path(__file__).resolve().parents[2] / "tutor-api"

    def configure(self) -> Config:
        """Copy the shipped ini and environment into an empty version tree."""
        script = self._root / "alembic"
        (script / "versions").mkdir(parents=True)
        for name in ("script.py.mako", "env.py"):
            (script / name).write_text(
                (self._source / "alembic" / name).read_text(encoding="utf-8"),
                encoding="utf-8",
            )
        ini = self._root / "alembic.ini"
        ini.write_text(self._ini(script), encoding="utf-8")
        return Config(str(ini))

    def _ini(self, script: Path) -> str:
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(self._source / "alembic.ini", encoding="utf-8")
        parser.set("alembic", "script_location", str(script))
        parser.set("alembic", "sqlalchemy.url", _CLOSED_PORT)
        buffer = self._root / "rendered.ini"
        with buffer.open("w", encoding="utf-8") as handle:
            parser.write(handle)
        return buffer.read_text(encoding="utf-8")


class TestRevisionFileNames:
    def test_authoring_a_revision_never_reaches_the_database(
        self, tmp_path: Path
    ) -> None:
        command.revision(RevisionTree(tmp_path).configure(), message="add note")
        written = list((tmp_path / "alembic" / "versions").glob("*.py"))
        assert len(written) == 1

    def test_filename_carries_the_utc_stamp_and_the_hash(self, tmp_path: Path) -> None:
        command.revision(RevisionTree(tmp_path).configure(), message="add note")
        written = next((tmp_path / "alembic" / "versions").glob("*.py"))
        match = _FILENAME.match(written.name)
        assert match is not None, written.name
        stamp, identifier, slug = match.groups()
        assert slug == "add_note"
        stamped = datetime.strptime(stamp, "%Y%m%d%H%M").replace(tzinfo=UTC)
        assert abs(stamped - datetime.now(UTC)) < timedelta(minutes=5)
        assert f"revision: str = '{identifier}'" in written.read_text(encoding="utf-8")

    def test_the_stamp_is_not_the_revision_id(self, tmp_path: Path) -> None:
        command.revision(RevisionTree(tmp_path).configure(), message="add note")
        written = next((tmp_path / "alembic" / "versions").glob("*.py"))
        stamp, identifier, _ = _FILENAME.match(written.name).groups()
        assert identifier != stamp

    def test_two_revisions_in_the_same_minute_do_not_collide(
        self, tmp_path: Path
    ) -> None:
        config = RevisionTree(tmp_path).configure()
        command.revision(config, message="add note")
        command.revision(config, message="add another note")
        written = sorted((tmp_path / "alembic" / "versions").glob("*.py"))
        assert len(written) == 2
        identifiers = {_FILENAME.match(path.name).group(2) for path in written}
        assert len(identifiers) == 2


class TestShippedRevisions:
    def test_every_shipped_revision_follows_the_template(self) -> None:
        versions = (
            Path(__file__).resolve().parents[2] / "tutor-api" / "alembic" / "versions"
        )
        names = sorted(path.name for path in versions.glob("*.py"))
        assert names
        for name in names:
            assert _FILENAME.match(name) is not None, name
