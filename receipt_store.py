"""Verify accepted receipts in the bot's evidence directory or private archive."""
from contextlib import contextmanager
import hashlib
import json
import os
import re
import stat


DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
MAX_RECEIPT = 64 * 1024
NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,79}")
SHA256 = re.compile(r"[a-f0-9]{64}")


@contextmanager
def directory(path, parent=None):
    fd = os.open(path, DIRECTORY, dir_fd=parent)
    try:
        yield fd
    finally:
        os.close(fd)


def read_file(folder, name, *, private=False):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=folder)
    with os.fdopen(fd, "rb") as file:
        attrs = os.fstat(file.fileno())
        if not stat.S_ISREG(attrs.st_mode) or attrs.st_size > MAX_RECEIPT:
            raise ValueError("receipt must be a regular file of at most 64 KiB")
        if private:
            require_private(attrs)
        data = file.read(MAX_RECEIPT + 1)
    if len(data) > MAX_RECEIPT:
        raise ValueError("receipt exceeds 64 KiB")
    return data


def require_private(attrs):
    if attrs.st_uid != os.geteuid() or attrs.st_mode & 0o077:
        raise ValueError("receipt archive must be private to the current user")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def verify(data, expected):
    try:
        result = json.loads(data)
    except (UnicodeError, ValueError) as exc:
        raise ValueError("receipt must contain valid JSON") from exc
    if not isinstance(result, dict) or any(result.get(k) != v for k, v in expected.items()):
        raise ValueError("receipt does not verify this item, criterion and outcome")
    if not isinstance(result.get("run_id"), str) or not result["run_id"].strip():
        raise ValueError("receipt requires a producer run_id")
    return result["run_id"]


def accept(bot, name, record, target):
    if not name:
        raise ValueError("a machine-produced --receipt is required")
    with directory(bot / "evidence") as hot:
        data = read_file(hot, name)
    expected = {"schema": 1, "kind": record["kind"], "id": record["id"], "criteria": record["criteria"],
                "result": "passed" if target == "completed" else "failed"}
    run_id = verify(data, expected)
    return json.dumps({"file": name, "sha256": digest(data), "run_id": run_id})


class Receipt:
    def __init__(self, db, kind, key, revision):
        row = db.execute("""SELECT state,evidence FROM ledger_history
            WHERE kind=? AND id=? AND revision=? AND state IN ('completed','failed')""",
                         (kind, key, revision)).fetchone()
        if row is None or row["evidence"] is None:
            raise ValueError("no accepted receipt at that outcome revision")
        try:
            self.reference = json.loads(row["evidence"])
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid ledger receipt reference") from exc
        if not isinstance(self.reference, dict):
            raise ValueError("invalid ledger receipt reference")
        self.filename = self.reference.get("file")
        self.sha256 = self.reference.get("sha256")
        run_id = self.reference.get("run_id")
        if (not isinstance(self.filename, str) or not NAME.fullmatch(self.filename)
                or not isinstance(self.sha256, str) or not SHA256.fullmatch(self.sha256)
                or not isinstance(run_id, str) or not run_id.strip()):
            raise ValueError("invalid ledger receipt reference")
        self.run_id = run_id
        self.expected = {"schema": 1, "kind": kind, "id": key,
                         "result": "passed" if row["state"] == "completed" else "failed"}

    def check(self, data, location):
        if digest(data) != self.sha256:
            raise ValueError(f"{location} receipt SHA-256 does not match the accepted revision")
        if verify(data, self.expected) != self.run_id:
            raise ValueError("receipt run_id does not match the accepted revision")
        return data

    def stored(self, archive):
        try:
            data = read_file(archive, self.sha256, private=True)
        except FileNotFoundError:
            return None
        return self.check(data, "archived")

    def hot(self, bot):
        try:
            with directory(bot / "evidence") as hot:
                return self.check(read_file(hot, self.filename), "hot")
        except FileNotFoundError as exc:
            raise ValueError("accepted receipt bytes are missing") from exc

    def store(self, archive, data):
        # A killed writer can leave this file. SQLite serializes CLI writers.
        pending = f".write-{self.sha256}"
        try:
            os.unlink(pending, dir_fd=archive)
        except FileNotFoundError:
            pass
        fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=archive)
        try:
            with os.fdopen(fd, "wb") as file:
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
            self.check(read_file(archive, pending, private=True), "staged archive")
            os.rename(pending, self.sha256, src_dir_fd=archive, dst_dir_fd=archive)
        finally:
            try:
                os.unlink(pending, dir_fd=archive)
            except FileNotFoundError:
                pass

    def release(self, bot, archive):
        pending = self.release_stage()
        try:
            with directory(bot / "evidence") as hot:
                return self.release_from(hot, archive, pending)
        except FileNotFoundError:
            # An absent hot directory is equivalent to an absent hot copy only
            # when there is no interrupted release to recover.
            try:
                os.stat(pending, dir_fd=archive, follow_symlinks=False)
            except FileNotFoundError:
                return "absent"
            raise

    def release_stage(self):
        return f".release-{self.sha256}-{self.filename}"

    def restore_staged(self, bot, state):
        pending = self.release_stage()
        try:
            with directory("evidence-archive", state) as archive:
                require_private(os.fstat(archive))
                attrs = os.stat(pending, dir_fd=archive, follow_symlinks=False)
                if not stat.S_ISREG(attrs.st_mode):
                    raise ValueError("staged release must be a regular file")
                with directory(bot / "evidence") as hot:
                    self.restore_hot(hot, archive, pending)
        except FileNotFoundError:
            pass

    def restore_hot(self, hot, archive, pending):
        try:
            os.link(pending, self.filename, src_dir_fd=archive, dst_dir_fd=hot, follow_symlinks=False)
        except FileExistsError:
            original = os.stat(pending, dir_fd=archive, follow_symlinks=False)
            current = os.stat(self.filename, dir_fd=hot, follow_symlinks=False)
            if not os.path.samestat(original, current):
                raise ValueError(f"release interrupted; newer hot file exists and {pending} is retained")
        os.fsync(hot)
        os.unlink(pending, dir_fd=archive)
        os.fsync(archive)

    def release_from(self, hot, archive, pending):
        try:
            os.stat(pending, dir_fd=archive, follow_symlinks=False)
        except FileNotFoundError:
            try:
                data = read_file(hot, self.filename)
            except FileNotFoundError:
                return "absent"
            if digest(data) != self.sha256:
                return "different"
            os.rename(self.filename, pending, src_dir_fd=hot, dst_dir_fd=archive)
        os.fsync(archive)
        os.fsync(hot)

        # Inspect the file actually moved. A producer may have changed the name
        # between the read and rename. Restore a replacement without overwriting
        # a newer publication. Keep the staged file if the name is occupied.
        try:
            self.check(read_file(archive, pending), "released")
        except ValueError as exc:
            self.restore_hot(hot, archive, pending)
            raise ValueError("receipt changed during release; restored the replacement") from exc
        os.unlink(pending, dir_fd=archive)
        os.fsync(archive)
        return "released"


def run(db, args, bot):
    receipt = Receipt(db, args.kind, args.id, args.revision)
    with directory(bot / "state") as state:
        if args.action == "resolve":
            try:
                with directory("evidence-archive", state) as archive:
                    require_private(os.fstat(archive))
                    stored = receipt.stored(archive)
            except FileNotFoundError:
                stored = None
            return receipt.hot(bot) if stored is None else stored

        if args.release_hot:
            pinned = db.execute("""
                SELECT 1 FROM ledger_history h JOIN ledger_items i USING(kind,id)
                WHERE i.state NOT IN ('completed','cancelled')
                AND json_extract(h.evidence,'$.file')=? LIMIT 1
            """, (receipt.filename,)).fetchone()
            if pinned:
                receipt.restore_staged(bot, state)
                raise ValueError("active or retryable work pins this receipt filename")
            path = f"evidence/{receipt.filename}"
            pinned = db.execute("""
                SELECT 1 FROM ledger_memory WHERE status='active'
                AND (expires IS NULL OR expires > CAST(strftime('%s', 'now') AS INTEGER))
                AND (source=? OR evidence=?) LIMIT 1
            """, (path, path)).fetchone()
            if pinned:
                receipt.restore_staged(bot, state)
                raise ValueError("active memory pins this receipt filename")
        try:
            os.mkdir("evidence-archive", 0o700, dir_fd=state)
        except FileExistsError:
            pass
        with directory("evidence-archive", state) as archive:
            require_private(os.fstat(archive))
            if receipt.stored(archive) is None:
                receipt.store(archive, receipt.hot(bot))
            os.fsync(archive)
            os.fsync(state)
            hot = receipt.release(bot, archive) if args.release_hot else "pinned"
            return {"reference": receipt.reference, "archived": True, "hot": hot}
