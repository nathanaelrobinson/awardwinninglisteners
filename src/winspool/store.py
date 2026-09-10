"""League persistence. One league document + a messages subcollection.
InMemoryStore for tests/dev; SqliteStore for the Pi (STORE=sqlite);
FirestoreStore for Cloud Run (STORE=firestore)."""
import json
import os
import sqlite3
import threading
import time
import uuid
from typing import Callable, Protocol

LEAGUE_ID = "2026"
MSG_CAP = 200


class Store(Protocol):
    def get(self) -> dict: ...
    def put(self, doc: dict) -> None: ...
    def update(self, fn: Callable[[dict], dict]) -> dict: ...
    def add_message(self, by: str, text: str) -> dict: ...
    def messages(self, since: float | None) -> list[dict]: ...
    def get_standings(self) -> dict | None: ...
    def put_standings(self, doc: dict) -> None: ...
    def get_preseason(self) -> dict | None: ...
    def put_preseason(self, doc: dict) -> None: ...
    def get_live(self) -> dict | None: ...
    def put_live(self, doc: dict) -> None: ...
    def get_sim_model(self) -> dict | None: ...
    def put_sim_model(self, doc: dict) -> None: ...
    def put_week(self, week: int, doc: dict) -> None: ...
    def list_weeks(self) -> list[dict]: ...
    def add_snapshot(self, snapshot: dict) -> str: ...
    def clear_messages(self) -> int: ...
    def list_snapshots(self) -> list[dict]: ...
    def add_odds(self, snapshot: dict) -> str: ...
    def put_odds(self, snapshot: dict) -> None: ...
    def odds_for_week(self, season: int, week: int) -> list[dict]: ...
    def latest_odds(self, season: int, week: int) -> list[dict]: ...
    def all_odds(self) -> list[dict]: ...


SNAPSHOT_CAP = 50


class InMemoryStore:
    def __init__(self, doc: dict | None = None):
        self._doc = doc
        self._msgs: list[dict] = []
        self._standings: dict | None = None
        self._preseason: dict | None = None
        self._sim_model: dict | None = None
        self._live: dict | None = None
        self._weeks: dict[int, dict] = {}
        self._snapshots: list[dict] = []
        self._odds: list[dict] = []
        self._lock = threading.Lock()

    def get(self) -> dict:
        if self._doc is None:
            raise LookupError("league not initialized")
        return self._doc

    def put(self, doc: dict) -> None:
        with self._lock:
            self._doc = doc

    def update(self, fn):
        with self._lock:
            self._doc = fn(self.get())
            return self._doc

    def add_message(self, by, text):
        m = {"id": uuid.uuid4().hex, "by": by, "text": text, "ts": time.time()}
        with self._lock:
            self._msgs.append(m)
        return m

    def messages(self, since):
        out = [m for m in self._msgs if since is None or m["ts"] > since]
        return out[-MSG_CAP:]

    def get_standings(self):
        return self._standings

    def put_standings(self, doc):
        with self._lock:
            self._standings = doc

    def get_preseason(self):
        return self._preseason

    def put_preseason(self, doc):
        with self._lock:
            self._preseason = doc

    def get_live(self):
        return self._live

    def put_live(self, doc):
        with self._lock:
            self._live = doc

    def get_sim_model(self):
        return self._sim_model

    def put_sim_model(self, doc):
        with self._lock:
            self._sim_model = doc

    def put_week(self, week, doc):
        with self._lock:
            self._weeks[int(week)] = doc

    def list_weeks(self):
        return [self._weeks[k] for k in sorted(self._weeks)]

    def add_snapshot(self, snapshot):
        sid = uuid.uuid4().hex
        with self._lock:
            self._snapshots.append({"id": sid, **snapshot})
        return sid

    def clear_messages(self):
        with self._lock:
            n = len(self._msgs)
            self._msgs = []
        return n

    def list_snapshots(self):
        return sorted(self._snapshots, key=lambda s: s["taken_at"], reverse=True)[:SNAPSHOT_CAP]

    def all_messages(self):
        """Every message, oldest first, uncapped. Export only."""
        return list(self._msgs)

    def all_snapshots(self):
        """Full snapshot docs, oldest first, uncapped. Export only."""
        return sorted(self._snapshots, key=lambda s: s["taken_at"])

    def put_message(self, m: dict) -> None:
        """Insert a message verbatim (id + ts preserved). Import only."""
        with self._lock:
            self._msgs = [x for x in self._msgs if x["id"] != m["id"]]
            self._msgs.append(dict(m))
            self._msgs.sort(key=lambda x: x["ts"])

    def put_snapshot(self, snap: dict) -> None:
        """Insert a snapshot verbatim (id preserved). Import only."""
        with self._lock:
            self._snapshots = [x for x in self._snapshots if x["id"] != snap["id"]]
            self._snapshots.append(dict(snap))

    # --- odds log (append only) ---

    def add_odds(self, snapshot: dict) -> str:
        row = {**snapshot, "id": snapshot.get("id") or uuid.uuid4().hex}
        with self._lock:
            self._odds.append(row)
        return row["id"]

    def put_odds(self, snapshot: dict) -> None:
        with self._lock:
            self._odds.append(dict(snapshot))

    def odds_for_week(self, season: int, week: int) -> list[dict]:
        rows = [r for r in self._odds
                if r["season"] == season and r["week"] == week]
        return sorted(rows, key=lambda r: r["fetched_at"])

    def latest_odds(self, season: int, week: int) -> list[dict]:
        best: dict[str, dict] = {}
        for r in self.odds_for_week(season, week):
            best[r["source"]] = r
        return list(best.values())

    def all_odds(self) -> list[dict]:
        return sorted(self._odds, key=lambda r: r["fetched_at"])


class FirestoreStore:
    def __init__(self, project: str | None = None):
        from google.cloud import firestore  # imported lazily: prod-only dep
        self._fs = firestore
        self._db = firestore.Client(project=project)
        self._ref = self._db.collection("leagues").document(LEAGUE_ID)

    def get(self):
        snap = self._ref.get()
        if not snap.exists:
            raise LookupError("league not initialized")
        return snap.to_dict()

    def put(self, doc):
        self._ref.set(doc)

    def update(self, fn):
        transaction = self._db.transaction(max_attempts=10)
        ref = self._ref

        @self._fs.transactional
        def _run(tx):
            snap = ref.get(transaction=tx)
            if not snap.exists:
                raise LookupError("league not initialized")
            new = fn(snap.to_dict())
            tx.set(ref, new)
            return new

        return _run(transaction)

    def add_message(self, by, text):
        m = {"by": by, "text": text, "ts": time.time()}
        _, ref = self._ref.collection("messages").add(m)
        return {"id": ref.id, **m}

    def messages(self, since):
        from google.cloud.firestore_v1.base_query import FieldFilter
        q = self._ref.collection("messages").order_by("ts")
        if since is not None:
            q = q.where(filter=FieldFilter("ts", ">", since))
        docs = list(q.limit_to_last(MSG_CAP).get()) if since is None else list(q.limit(MSG_CAP).get())
        return [{"id": d.id, **d.to_dict()} for d in docs]

    def get_standings(self):
        snap = self._ref.collection("cache").document("standings").get()
        return snap.to_dict() if snap.exists else None

    def put_standings(self, doc):
        self._ref.collection("cache").document("standings").set(doc)

    def get_preseason(self):
        snap = self._ref.collection("cache").document("preseason").get()
        return snap.to_dict() if snap.exists else None

    def put_preseason(self, doc):
        self._ref.collection("cache").document("preseason").set(doc)

    def get_live(self):
        snap = self._ref.collection("cache").document("live").get()
        return snap.to_dict() if snap.exists else None

    def put_live(self, doc):
        self._ref.collection("cache").document("live").set(doc)

    def get_sim_model(self):
        snap = self._ref.collection("cache").document("sim_model").get()
        return snap.to_dict() if snap.exists else None

    def put_sim_model(self, doc):
        self._ref.collection("cache").document("sim_model").set(doc)

    def put_week(self, week, doc):
        self._ref.collection("weeks").document(str(int(week))).set(doc)

    def list_weeks(self):
        docs = [d.to_dict() for d in self._ref.collection("weeks").stream()]
        return sorted(docs, key=lambda d: d["week"])

    def add_snapshot(self, snapshot):
        _, ref = self._ref.collection("snapshots").add(snapshot)
        return ref.id

    def clear_messages(self):
        docs = list(self._ref.collection("messages").stream())
        n = 0
        for i in range(0, len(docs), 400):
            batch = self._db.batch()
            for d in docs[i:i + 400]:
                batch.delete(d.reference)
            batch.commit()
            n += len(docs[i:i + 400])
        return n

    def list_snapshots(self):
        q = self._ref.collection("snapshots").order_by(
            "taken_at", direction=self._fs.Query.DESCENDING).limit(SNAPSHOT_CAP)
        return [{"id": d.id, **d.to_dict()} for d in q.get()]

    def all_messages(self):
        """Every message, oldest first, uncapped (MSG_CAP does not apply). Export only."""
        q = self._ref.collection("messages").order_by("ts")
        return [{"id": d.id, **d.to_dict()} for d in q.stream()]

    def all_snapshots(self):
        """Full snapshot docs, oldest first, uncapped. Export only."""
        q = self._ref.collection("snapshots").order_by("taken_at")
        return [{"id": d.id, **d.to_dict()} for d in q.stream()]

    # --- odds log (append only) ---

    def _odds_col(self):
        return self._ref.collection("odds")

    def add_odds(self, snapshot: dict) -> str:
        row = {**snapshot, "id": snapshot.get("id") or uuid.uuid4().hex}
        self.put_odds(row)
        return row["id"]

    def put_odds(self, snapshot: dict) -> None:
        self._odds_col().document(snapshot["id"]).set(snapshot)

    def odds_for_week(self, season: int, week: int) -> list[dict]:
        q = (self._odds_col().where("season", "==", int(season))
             .where("week", "==", int(week)).order_by("fetched_at"))
        return [d.to_dict() for d in q.stream()]

    def latest_odds(self, season: int, week: int) -> list[dict]:
        best: dict[str, dict] = {}
        for r in self.odds_for_week(season, week):
            best[r["source"]] = r
        return list(best.values())

    def all_odds(self) -> list[dict]:
        return [d.to_dict() for d in self._odds_col().order_by("fetched_at").stream()]


class SqliteStore:
    """Single-file SQLite store. Same semantics as FirestoreStore, no cloud.

    One connection in autocommit mode (isolation_level=None) guarded by a lock,
    so `update` can drive its own BEGIN IMMEDIATE ... COMMIT. That write lock is
    what gives us Firestore's "one pick at a time" transactional guarantee.
    """

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS league    (id TEXT PRIMARY KEY, doc TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS messages  (id TEXT PRIMARY KEY, "by" TEXT, text TEXT, ts REAL);
    CREATE INDEX IF NOT EXISTS messages_ts ON messages(ts);
    CREATE TABLE IF NOT EXISTS snapshots (id TEXT PRIMARY KEY, taken_at REAL, reason TEXT,
                                          n_picks INTEGER, status TEXT, doc TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS snapshots_taken_at ON snapshots(taken_at);
    CREATE TABLE IF NOT EXISTS kv        (k TEXT PRIMARY KEY, v TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS weeks     (week INTEGER PRIMARY KEY, doc TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS odds (id TEXT PRIMARY KEY, season INTEGER NOT NULL,
                                     week INTEGER NOT NULL, source TEXT NOT NULL,
                                     fetched_at REAL NOT NULL, doc TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS odds_week ON odds(season, week, fetched_at);
    """

    def __init__(self, path: str | os.PathLike):
        path = str(path)
        if path != ":memory:":
            parent = os.path.dirname(os.path.abspath(path))
            os.makedirs(parent, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA busy_timeout=5000")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.executescript(self.SCHEMA)
        self._lock = threading.Lock()

    # --- league doc ---

    def get(self) -> dict:
        row = self._db.execute("SELECT doc FROM league WHERE id=?", (LEAGUE_ID,)).fetchone()
        if row is None:
            raise LookupError("league not initialized")
        return json.loads(row[0])

    def put(self, doc: dict) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO league (id, doc) VALUES (?, ?)",
                             (LEAGUE_ID, json.dumps(doc)))

    def update(self, fn):
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute("SELECT doc FROM league WHERE id=?",
                                       (LEAGUE_ID,)).fetchone()
                if row is None:
                    raise LookupError("league not initialized")
                new = fn(json.loads(row[0]))
                self._db.execute("UPDATE league SET doc=? WHERE id=?",
                                 (json.dumps(new), LEAGUE_ID))
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            self._db.execute("COMMIT")
            return new

    # --- messages ---

    def add_message(self, by: str, text: str) -> dict:
        m = {"id": uuid.uuid4().hex, "by": by, "text": text, "ts": time.time()}
        with self._lock:
            self._db.execute('INSERT INTO messages (id, "by", text, ts) VALUES (?, ?, ?, ?)',
                             (m["id"], m["by"], m["text"], m["ts"]))
        return m

    def messages(self, since: float | None) -> list[dict]:
        # Oldest-first either way: without `since` the newest MSG_CAP, with it the
        # first MSG_CAP after `since` — same contract as the Firestore path.
        if since is None:
            rows = self._db.execute(
                'SELECT id, "by", text, ts FROM messages ORDER BY ts DESC, rowid DESC LIMIT ?',
                (MSG_CAP,)).fetchall()
            rows = rows[::-1]
        else:
            rows = self._db.execute(
                'SELECT id, "by", text, ts FROM messages WHERE ts > ? '
                'ORDER BY ts, rowid LIMIT ?', (since, MSG_CAP)).fetchall()
        return [{"id": r[0], "by": r[1], "text": r[2], "ts": r[3]} for r in rows]

    def all_messages(self) -> list[dict]:
        """Every message, oldest first, uncapped. Export only."""
        rows = self._db.execute(
            'SELECT id, "by", text, ts FROM messages ORDER BY ts, rowid').fetchall()
        return [{"id": r[0], "by": r[1], "text": r[2], "ts": r[3]} for r in rows]

    def clear_messages(self) -> int:
        with self._lock:
            cur = self._db.execute("DELETE FROM messages")
            return cur.rowcount

    # --- standings cache ---

    def get_standings(self) -> dict | None:
        row = self._db.execute("SELECT v FROM kv WHERE k='standings'").fetchone()
        return json.loads(row[0]) if row else None

    def put_standings(self, doc: dict) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO kv (k, v) VALUES ('standings', ?)",
                             (json.dumps(doc),))

    def get_preseason(self) -> dict | None:
        row = self._db.execute("SELECT v FROM kv WHERE k='preseason'").fetchone()
        return json.loads(row[0]) if row else None

    def put_preseason(self, doc: dict) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO kv (k, v) VALUES ('preseason', ?)",
                             (json.dumps(doc),))

    def get_live(self) -> dict | None:
        row = self._db.execute("SELECT v FROM kv WHERE k='live'").fetchone()
        return json.loads(row[0]) if row else None

    def put_live(self, doc: dict) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO kv (k, v) VALUES ('live', ?)",
                             (json.dumps(doc),))

    def get_sim_model(self) -> dict | None:
        row = self._db.execute("SELECT v FROM kv WHERE k='sim_model'").fetchone()
        return json.loads(row[0]) if row else None

    def put_sim_model(self, doc: dict) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO kv (k, v) VALUES ('sim_model', ?)",
                             (json.dumps(doc),))

    def put_week(self, week: int, doc: dict) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO weeks (week, doc) VALUES (?, ?)",
                             (int(week), json.dumps(doc)))

    def list_weeks(self) -> list[dict]:
        rows = self._db.execute("SELECT doc FROM weeks ORDER BY week").fetchall()
        return [json.loads(r[0]) for r in rows]

    # --- snapshots ---

    def add_snapshot(self, snapshot: dict) -> str:
        sid = uuid.uuid4().hex
        with self._lock:
            self._db.execute(
                "INSERT INTO snapshots (id, taken_at, reason, n_picks, status, doc) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (sid, snapshot.get("taken_at"), snapshot.get("reason"),
                 snapshot.get("n_picks"), snapshot.get("status"), json.dumps(snapshot)))
        return sid

    def list_snapshots(self) -> list[dict]:
        rows = self._db.execute(
            "SELECT id, taken_at, reason, n_picks, status FROM snapshots "
            "ORDER BY taken_at DESC, rowid DESC LIMIT ?", (SNAPSHOT_CAP,)).fetchall()
        return [{"id": r[0], "taken_at": r[1], "reason": r[2],
                 "n_picks": r[3], "status": r[4]} for r in rows]

    def all_snapshots(self) -> list[dict]:
        """Full snapshot docs, oldest first, uncapped. Export only."""
        rows = self._db.execute(
            "SELECT id, doc FROM snapshots ORDER BY taken_at, rowid").fetchall()
        return [{"id": r[0], **json.loads(r[1])} for r in rows]

    # --- import helpers (preserve ids and timestamps) ---

    def put_message(self, m: dict) -> None:
        """Insert a message verbatim (id + ts preserved). Import only."""
        with self._lock:
            self._db.execute(
                'INSERT OR REPLACE INTO messages (id, "by", text, ts) VALUES (?, ?, ?, ?)',
                (m["id"], m.get("by"), m.get("text"), m.get("ts")))

    def put_snapshot(self, snap: dict) -> None:
        """Insert a snapshot verbatim (id preserved). Import only."""
        doc = {k: v for k, v in snap.items() if k != "id"}
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO snapshots (id, taken_at, reason, n_picks, status, doc) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (snap["id"], snap.get("taken_at"), snap.get("reason"),
                 snap.get("n_picks"), snap.get("status"), json.dumps(doc)))

    # --- odds log (append only) ---

    def add_odds(self, snapshot: dict) -> str:
        row = {**snapshot, "id": snapshot.get("id") or uuid.uuid4().hex}
        self.put_odds(row)
        return row["id"]

    def put_odds(self, snapshot: dict) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO odds (id, season, week, source, fetched_at, doc) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (snapshot["id"], int(snapshot["season"]), int(snapshot["week"]),
                 snapshot["source"], float(snapshot["fetched_at"]),
                 json.dumps(snapshot)))

    def odds_for_week(self, season: int, week: int) -> list[dict]:
        rows = self._db.execute(
            "SELECT doc FROM odds WHERE season=? AND week=? ORDER BY fetched_at, rowid",
            (int(season), int(week))).fetchall()
        return [json.loads(r[0]) for r in rows]

    def latest_odds(self, season: int, week: int) -> list[dict]:
        best: dict[str, dict] = {}
        for r in self.odds_for_week(season, week):
            best[r["source"]] = r
        return list(best.values())

    def all_odds(self) -> list[dict]:
        rows = self._db.execute(
            "SELECT doc FROM odds ORDER BY fetched_at, rowid").fetchall()
        return [json.loads(r[0]) for r in rows]

    def close(self) -> None:
        self._db.close()


_STORE: Store | None = None


def get_store() -> Store:
    global _STORE
    if _STORE is None:
        kind = os.environ.get("STORE")
        if kind == "firestore":
            _STORE = FirestoreStore(os.environ.get("GOOGLE_CLOUD_PROJECT"))
        elif kind == "sqlite":
            _STORE = SqliteStore(os.environ.get("WINSPOOL_DB") or "data/league.db")
        else:
            _STORE = InMemoryStore()
    return _STORE


def set_store(store: Store | None) -> None:
    global _STORE
    _STORE = store
