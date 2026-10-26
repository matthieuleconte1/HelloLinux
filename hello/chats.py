"""Historique des conversations avec l'IA (Chats.swift), gardé dans ~/.local/share/hello/chats.json (0600).

Une conversation : la première demande et ses questions de suite. Un échange (« turn ») : la demande et ce
qui en est sorti (réponse, résumé d'une action, ou prompt envoyé au terminal au niveau 3)."""
import os
import threading
import time
import uuid

from .settings import DATA_DIR, load_json, save_json

LIMIT = 200


def new_turn(level, request, answer, kind, steps=(), attachments=(), session_id=None, engine="hermes"):
    """kind : answer | done | code."""
    return {"id": str(uuid.uuid4()), "date": time.time(), "level": level, "request": request, "answer": answer,
            "kind": kind, "steps": list(steps), "attachments": list(attachments), "sessionID": session_id,
            "engine": engine}


class Conversation:
    def __init__(self, turns=None, cid=None):
        self.id = cid or str(uuid.uuid4())
        self.turns = list(turns or [])

    @classmethod
    def load(cls, data):
        return cls([t for t in data.get("turns", []) if isinstance(t, dict) and t.get("request") is not None],
                   data.get("id"))

    def dump(self):
        return {"id": self.id, "turns": self.turns}

    @property
    def title(self):
        return self.turns[0]["request"] if self.turns else ""

    @property
    def updated(self):
        return self.turns[-1]["date"] if self.turns else 0

    @property
    def transcript(self):
        """Échanges précédents, joints aux prompts pour que l'IA reprenne le fil (les plus récents, réponses abrégées)."""
        lines = []
        for turn in self.turns[-8:]:
            answer = turn.get("answer") or ""
            if len(answer) > 1500:
                answer = answer[:1500] + "…"
            files = f"\n(attached: {', '.join(turn['attachments'])})" if turn.get("attachments") else ""
            what = "sent to a coding session in the terminal" if turn.get("kind") == "code" else "answered"
            lines.append(f"User: {turn['request']}{files}\nAssistant ({what}): {answer}")
        return "\n\n".join(lines)


class ChatStore:
    _path = os.path.join(DATA_DIR, "chats.json")
    conversations = []
    _lock = threading.Lock()

    @classmethod
    def load(cls):
        data = load_json(cls._path, [])
        cls.conversations = [Conversation.load(c) for c in data if isinstance(c, dict)] if isinstance(data, list) else []

    @classmethod
    def save(cls, conversation):
        """Enregistre la conversation (nouvelle ou prolongée) et la remonte en tête."""
        if not conversation.turns:
            return
        cls.conversations = [conversation] + [c for c in cls.conversations if c.id != conversation.id]
        del cls.conversations[LIMIT:]
        cls._write()

    @classmethod
    def delete(cls, cid):
        cls.conversations = [c for c in cls.conversations if c.id != cid]
        cls._write()

    @classmethod
    def clear(cls):
        cls.conversations = []
        cls._write()

    @classmethod
    def search(cls, query):
        q = query.strip().lower()
        if not q:
            return list(cls.conversations)
        return [c for c in cls.conversations
                if any(q in (t.get("request") or "").lower() or q in (t.get("answer") or "").lower() for t in c.turns)]

    @classmethod
    def _write(cls):
        snapshot = [c.dump() for c in cls.conversations]

        def write():
            with cls._lock:
                save_json(cls._path, snapshot, private=True)
        threading.Thread(target=write, daemon=True).start()


ChatStore.load()
