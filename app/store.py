"""Durable SQLite inbox/outbox; each webhook is committed before acknowledgement."""

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from app.messages import HELP_REPLY, SALES_REPLY, intent
from app.payloads import DeliveryStatus, Message

WINDOW_SECONDS = 24 * 60 * 60
# Stop slightly before the actual window boundary to allow network transit time.
SEND_MARGIN_SECONDS = 60


class Store:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS contacts (
                    recipient TEXT PRIMARY KEY,
                    paused INTEGER NOT NULL DEFAULT 0,
                    opted_out INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    inbound_id TEXT PRIMARY KEY,
                    recipient TEXT NOT NULL,
                    inbound_at INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    reply TEXT,
                    state TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    ready_at REAL NOT NULL,
                    lease_until REAL,
                    outbound_id TEXT,
                    error TEXT,
                    delivery_status TEXT,
                    delivery_at INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS jobs_ready ON jobs(state, ready_at);
                CREATE INDEX IF NOT EXISTS jobs_outbound ON jobs(outbound_id);
                CREATE TABLE IF NOT EXISTS help_requests (
                    inbound_id TEXT PRIMARY KEY,
                    recipient TEXT NOT NULL,
                    received_at INTEGER NOT NULL,
                    body TEXT NOT NULL,
                    resolved INTEGER NOT NULL DEFAULT 0
                );
            """)

    def ingest(self, messages: list[Message], statuses: list[DeliveryStatus]):
        now = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for message in messages:
                text = message.text.body if message.type == "text" and message.text else ""
                kind = intent(text)
                reply = {"sales": SALES_REPLY, "start": SALES_REPLY, "help": HELP_REPLY}.get(kind)
                fresh = now - WINDOW_SECONDS + SEND_MARGIN_SECONDS < message.timestamp <= now + 300
                state = "pending" if reply and fresh else "ignored"
                inserted = db.execute(
                    """INSERT OR IGNORE INTO jobs
                       (inbound_id, recipient, inbound_at, kind, reply, state, ready_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (message.id, message.sender, message.timestamp, kind, reply, state, now),
                ).rowcount
                if not inserted:
                    continue
                db.execute(
                    "INSERT OR IGNORE INTO contacts(recipient) VALUES (?)", (message.sender,)
                )
                contact = db.execute(
                    "SELECT * FROM contacts WHERE recipient = ?", (message.sender,)
                ).fetchone()
                # Old messages cannot resume automation, opt in, or reopen handoffs.
                if not fresh:
                    continue
                if kind == "stop":
                    db.execute(
                        "UPDATE contacts SET opted_out = 1 WHERE recipient = ?", (message.sender,)
                    )
                    db.execute(
                        """UPDATE jobs SET state = 'suppressed' WHERE recipient = ?
                           AND state IN ('pending', 'retry')""",
                        (message.sender,),
                    )
                elif kind == "start":
                    db.execute(
                        "UPDATE contacts SET opted_out = 0, paused = 0 WHERE recipient = ?",
                        (message.sender,),
                    )
                    db.execute(
                        "UPDATE help_requests SET resolved = 1 WHERE recipient = ?",
                        (message.sender,),
                    )
                elif not contact["opted_out"]:
                    if kind == "help" or contact["paused"]:
                        db.execute(
                            "UPDATE contacts SET paused = 1 WHERE recipient = ?", (message.sender,)
                        )
                        db.execute(
                            "INSERT INTO help_requests VALUES (?, ?, ?, ?, 0)",
                            (
                                message.id,
                                message.sender,
                                message.timestamp,
                                text or f"[{message.type} message; media is not downloaded]",
                            ),
                        )
                        db.execute(
                            """UPDATE jobs SET state = 'suppressed' WHERE recipient = ?
                               AND kind != 'help' AND state IN ('pending', 'retry')""",
                            (message.sender,),
                        )
                    if contact["paused"] and kind != "help":
                        state = "suppressed"
                if contact["opted_out"] and kind != "start":
                    state = "suppressed"
                db.execute("UPDATE jobs SET state = ? WHERE inbound_id = ?", (state, message.id))

            for status in statuses:
                # The callback identifier also reconciles a response lost after Meta accepted it.
                error = None
                if status.errors:
                    error = f"delivery_code:{status.errors[0].get('code', 'unknown')}"
                db.execute(
                    """UPDATE jobs SET delivery_status = ?, delivery_at = ?,
                       outbound_id = ?, error = COALESCE(?, error),
                       state = CASE WHEN state IN ('sending', 'uncertain')
                           THEN 'sent' ELSE state END
                       WHERE (outbound_id = ? OR inbound_id = ?)
                       AND (delivery_at < ? OR (delivery_at = ? AND
                           CASE ? WHEN 'read' THEN 3 WHEN 'delivered' THEN 2
                               WHEN 'sent' THEN 1 ELSE 0 END >=
                           CASE delivery_status WHEN 'read' THEN 3 WHEN 'delivered' THEN 2
                               WHEN 'sent' THEN 1 ELSE 0 END))""",
                    (
                        status.status,
                        status.timestamp,
                        status.id,
                        error,
                        status.id,
                        status.biz_opaque_callback_data,
                        status.timestamp,
                        status.timestamp,
                        status.status,
                    ),
                )

    def claim(self):
        now = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """UPDATE jobs SET state = 'uncertain', error = 'worker_interrupted'
                   WHERE state = 'sending' AND lease_until < ?""",
                (now,),
            )
            db.execute(
                """UPDATE jobs SET state = 'expired' WHERE state IN ('pending', 'retry')
                   AND inbound_at <= ?""",
                (now - WINDOW_SECONDS + SEND_MARGIN_SECONDS,),
            )
            db.execute("""
                UPDATE jobs SET state = 'suppressed'
                WHERE state IN ('pending', 'retry') AND EXISTS (
                    SELECT 1 FROM contacts c WHERE c.recipient = jobs.recipient
                    AND (c.opted_out = 1 OR (c.paused = 1 AND jobs.kind != 'help'))
                )
            """)
            row = db.execute(
                """SELECT * FROM jobs WHERE state IN ('pending', 'retry') AND ready_at <= ?
                   ORDER BY ready_at, rowid LIMIT 1""",
                (now,),
            ).fetchone()
            if row is None:
                return None
            db.execute(
                """UPDATE jobs SET state = 'sending', attempts = attempts + 1,
                   lease_until = ? WHERE inbound_id = ?""",
                (now + 120, row["inbound_id"]),
            )
            job = dict(row)
            job["attempts"] += 1
            return job

    def finish(self, inbound_id: str, state: str, *, outbound_id=None, error=None, delay=0):
        with self.connect() as db:
            db.execute(
                """UPDATE jobs SET state = ?, outbound_id = COALESCE(?, outbound_id),
                   error = ?, ready_at = ?, lease_until = NULL
                   WHERE inbound_id = ? AND state = 'sending'""",
                (state, outbound_id, error, time.time() + delay, inbound_id),
            )

    def retry_expired_token_failures(self) -> int:
        """Requeue only jobs that failed before any POST was attempted."""
        now = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            result = db.execute(
                """UPDATE jobs SET state = 'pending', error = NULL, ready_at = ?
                   WHERE state = 'failed'
                   AND error = 'sender_check_http_401_meta_190'
                   AND inbound_at > ?""",
                (now, now - WINDOW_SECONDS + SEND_MARGIN_SECONDS),
            )
            return result.rowcount

    def ready(self):
        with self.connect() as db:
            db.execute("SELECT 1 FROM jobs LIMIT 1").fetchone()
