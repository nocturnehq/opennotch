"""Clipboard history: newest first, at most `limit` unpinned clips, pinned clips are never evicted."""
import json
import os
import time

MAX_CLIP_CHARS = 100_000


class ClipStore:
    def __init__(self, path, limit=50, keep_hours=None):
        self.keep_s = keep_hours * 3600 if keep_hours else None
        self.path = path
        self.limit = limit
        self.items = []  # dicts: {"text", "pinned", "ts"}
        self._load()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            self.items = [
                {"text": d["text"], "pinned": bool(d.get("pinned")), "ts": float(d.get("ts", 0))}
                for d in data if isinstance(d, dict) and isinstance(d.get("text"), str)
            ]
            self._trim()
        except (OSError, ValueError, TypeError, KeyError):
            self.items = []

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        # clips can hold private text: owner-only file, atomic replace so a crash never truncates history
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self.items, f)
        os.replace(tmp, self.path)

    def _trim(self):
        if self.keep_s:  # unpinned clips older than the keep time go, as in NotchPixel
            cutoff = time.time() - self.keep_s
            self.items = [it for it in self.items if it["pinned"] or it["ts"] >= cutoff]
        unpinned = 0
        kept = []
        for it in self.items:
            if not it["pinned"]:
                unpinned += 1
                if unpinned > self.limit:
                    continue
            kept.append(it)
        self.items = kept

    def add(self, text):
        """Add a clip (or move an existing identical one to the top). Returns True if the list changed."""
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_CLIP_CHARS:
            return False
        if self.items and self.items[0]["text"] == text:
            return False
        old = next((it for it in self.items if it["text"] == text), None)
        if old:
            self.items.remove(old)
        self.items.insert(0, {"text": text, "pinned": old["pinned"] if old else False, "ts": time.time()})
        self._trim()
        return True

    def toggle_pin(self, text):
        for it in self.items:
            if it["text"] == text:
                it["pinned"] = not it["pinned"]
        self._trim()

    def remove(self, text):
        self.items = [it for it in self.items if it["text"] != text]

    def clear_unpinned(self):
        self.items = [item for item in self.items if item["pinned"]]
        self.save()

    def search(self, query=""):
        q = query.strip().lower()
        hits = [it for it in self.items if q in it["text"].lower()]
        return sorted(hits, key=lambda it: not it["pinned"])  # pinned first, otherwise newest first (stable)
