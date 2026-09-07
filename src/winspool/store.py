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


class InMemoryStore:
    def __init__(self, doc: dict | None = None):
        self._doc = doc
        self._msgs: list[dict] = []
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
        transaction = self._db.transaction()
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
        q = self._ref.collection("messages").order_by("ts")
        if since is not None:
            q = q.where("ts", ">", since)
        docs = list(q.limit_to_last(MSG_CAP).get()) if since is None else list(q.limit(MSG_CAP).get())
        return [{"id": d.id, **d.to_dict()} for d in docs]


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
