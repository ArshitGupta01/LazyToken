"""A small offline notebook used only as a benchmark starting fixture."""

import json
from pathlib import Path


class Notebook:
    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, entries):
        self.path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")

    def add(self, title, body, tags=()):
        entries = self.load()
        item = {
            "id": len(entries) + 1,
            "title": title,
            "body": body,
            "tags": list(tags),
            "archived": False,
        }
        entries.append(item)
        self.save(entries)
        return item

    def find(self, term):
        query = term.casefold()
        return [
            entry
            for entry in self.load()
            if query in entry["title"].casefold() or query in entry["body"].casefold()
        ]

    def archive(self, entry_id):
        entries = self.load()
        for entry in entries:
            if entry["id"] == entry_id:
                entry["archived"] = True
                self.save(entries)
                return True
        return False
