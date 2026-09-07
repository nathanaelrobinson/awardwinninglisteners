"""League persistence. One league document + a messages subcollection.
InMemoryStore for tests/dev; FirestoreStore for prod (STORE=firestore)."""
import os
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
    def add_snapshot(self, snapshot: dict) -> str: ...
    def clear_messages(self) -> int: ...
    def list_snapshots(self) -> list[dict]: ...


SNAPSHOT_CAP = 50


class InMemoryStore:
    def __init__(self, doc: dict | None = None):
        self._doc = doc
        self._msgs: list[dict] = []
        self._standings: dict | None = None
        self._snapshots: list[dict] = []
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


_STORE: Store | None = None


def get_store() -> Store:
    global _STORE
    if _STORE is None:
        if os.environ.get("STORE") == "firestore":
            _STORE = FirestoreStore(os.environ.get("GOOGLE_CLOUD_PROJECT"))
        else:
            _STORE = InMemoryStore()
    return _STORE


def set_store(store: Store | None) -> None:
    global _STORE
    _STORE = store
