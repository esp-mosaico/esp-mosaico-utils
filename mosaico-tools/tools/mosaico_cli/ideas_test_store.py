"""Persistent state for the explicitly local Ideas integration server."""
from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import time
import uuid

from .ideas_content import ContentError, digest, encoded, require, version_satisfies
from .ideas_release import validate_release


DEFAULT_AUTHOR = "Mosaico Test Account"


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        for name in ("archives", "blobs", "temporary"):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS agent_projects (
                  id TEXT PRIMARY KEY, owner TEXT NOT NULL, draft_archive TEXT,
                  app_number TEXT UNIQUE);
                CREATE TABLE IF NOT EXISTS agent_releases (
                  seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
                  application TEXT NOT NULL, code TEXT NOT NULL, version TEXT NOT NULL,
                  root_hash TEXT NOT NULL, firmware TEXT NOT NULL, profile TEXT NOT NULL,
                  published REAL NOT NULL, UNIQUE(application, version));
                CREATE TABLE IF NOT EXISTS agent_release_files (
                  release TEXT NOT NULL, hash TEXT NOT NULL, PRIMARY KEY(release, hash));
                CREATE TABLE IF NOT EXISTS settings (name TEXT PRIMARY KEY, value TEXT NOT NULL);
            ''')

    def account_id(self, initial_id):
        """One fixture account, stable across test-token rotation and restart."""
        with self.db() as db:
            db.execute("INSERT OR IGNORE INTO settings VALUES ('account',?)", (initial_id,))
            return db.execute("SELECT value FROM settings WHERE name='account'").fetchone()[0]

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.root / "state.sqlite3", timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def put(self, group, data):
        name = digest(data)
        target = self.root / group / name
        if target.exists():
            require(digest(target.read_bytes()) == name, "Immutable object was modified", code="IMMUTABILITY_CONFLICT")
        else:
            temporary = self.root / "temporary" / uuid.uuid4().hex
            try:
                with temporary.open("xb") as file:
                    file.write(data)
                    file.flush()
                    import os
                    os.fsync(file.fileno())
                # Concurrent writers of the same hash have exactly the same bytes.
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        return name

    def save_draft(self, owner, raw, public_id=None):
        release = validate_release(raw)
        archive = self.put("archives", raw)
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            if public_id is None:
                public_id = "app-" + uuid.uuid4().hex
                db.execute("INSERT INTO agent_projects(id,owner) VALUES (?,?)", (public_id, owner))
            app = db.execute("SELECT * FROM agent_projects WHERE id=?", (public_id,)).fetchone()
            require(app is not None, "Unknown project", code="APPLICATION_NOT_FOUND")
            require(app["owner"] == owner, "Project belongs to another owner", code="FORBIDDEN")
            require(not db.execute("SELECT 1 FROM agent_releases WHERE application=? AND version=?",
                                   (public_id, release.firmware["release"])).fetchone(),
                    "This application version is already published", code="VERSION_ALREADY_PUBLISHED")
            # No CAS: the last successfully saved upload replaces the draft.
            db.execute("UPDATE agent_projects SET draft_archive=? WHERE id=?", (archive, public_id))
            return {"public_id": public_id, "status": "draft", "app_number": app["app_number"],
                    "title": release.manifest["project"]["title"]}

    def publish(self, public_id, *, author=DEFAULT_AUTHOR):
        """Fixture administrator action: allocate identity and publish atomically.

        The production site additionally owns submission and approval. No Agent
        endpoint can invoke this operation, and uploads never allocate a code.
        """
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            app = db.execute("SELECT * FROM agent_projects WHERE id=?", (public_id,)).fetchone()
            require(app is not None and app["draft_archive"], "No project draft", code="APPLICATION_NOT_FOUND")
            release = validate_release(self.root / "archives" / app["draft_archive"])
            require(release.archive_sha256 == app["draft_archive"], "Archive storage changed", code="ARCHIVE_HASH_MISMATCH")
            version = release.firmware["release"]
            require(not db.execute("SELECT 1 FROM agent_releases WHERE application=? AND version=?",
                                   (public_id, version)).fetchone(),
                    "This application version is already published", code="VERSION_ALREADY_PUBLISHED")
            code = app["app_number"]
            if code is None:
                previous = db.execute("SELECT MAX(CAST(app_number AS INTEGER)) FROM agent_projects").fetchone()[0]
                number = max(201000, (previous or 200999) + 1)
                require(number <= 299999, "No application codes available", code="SERVICE_UNAVAILABLE")
                code = str(number)
            release_id = "release-" + uuid.uuid4().hex
            _, files = release.device_release(public_id, code, release_id, author=author)
            hashes = {self.put("blobs", data) for data in files.values()}
            db.execute("INSERT INTO agent_releases(id,application,code,version,root_hash,firmware,profile,published) "
                       "VALUES (?,?,?,?,?,?,?,?)",
                       (release_id, public_id, code, version, digest(files["manifest.json"]),
                        encoded(release.firmware).decode(), release.manifest["device"]["profile"], time.time()))
            db.executemany("INSERT INTO agent_release_files VALUES (?,?)", [(release_id, h) for h in hashes])
            db.execute("UPDATE agent_projects SET app_number=?,draft_archive=NULL WHERE id=?", (code, public_id))
            return {"public_id": public_id, "app_number": code, "release_id": release_id, "status": "approved"}

    def manifest(self, code, capabilities=None, release_id=None):
        with self.db() as db:
            if release_id:
                rows = db.execute("SELECT * FROM agent_releases WHERE code=? AND id=?", (code, release_id)).fetchall()
            else:
                rows = db.execute("SELECT * FROM agent_releases WHERE code=? ORDER BY published DESC,seq DESC", (code,)).fetchall()
            require(rows, "Published release not found", code="APPLICATION_NOT_FOUND")
            for row in rows:
                firmware = json.loads(row["firmware"])
                if capabilities and not (row["profile"] == capabilities["profile"]
                        and firmware["target"]["chip_id"] == capabilities["chip_id"]
                        and firmware["target"]["flash_size"] == capabilities["flash_size"]
                        and version_satisfies(capabilities["recovery_version"], firmware.get("minimum_recovery_version"))):
                    continue
                return (self.root / "blobs" / row["root_hash"]).read_bytes(), row["root_hash"]
        raise ContentError("NO_COMPATIBLE_RELEASE", "No published release matches the device")

    def blob(self, sha256):
        with self.db() as db:
            visible = db.execute("SELECT 1 FROM agent_release_files f JOIN agent_releases r ON r.id=f.release WHERE f.hash=? LIMIT 1", (sha256,)).fetchone()
        require(visible, "Published file not found", code="FILE_NOT_FOUND")
        return self.root / "blobs" / sha256
