r"""Local library of saved signatures / initials.

Signatures are stored as transparent PNGs under
%APPDATA%\PDFAnnotator\signatures\, indexed by a JSON file so the app can
list, reuse and delete them like a rubber-stamp collection.
"""
import json
import os
import uuid

from PySide6.QtGui import QImage


def default_store_dir():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "PDFAnnotator", "signatures")


class SignatureStore:
    def __init__(self, store_dir=None):
        self.dir = store_dir or default_store_dir()
        os.makedirs(self.dir, exist_ok=True)
        self.index_path = os.path.join(self.dir, "index.json")
        self.items = self._load()

    def _load(self):
        if not os.path.exists(self.index_path):
            return []
        try:
            with open(self.index_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []

    def _save_index(self):
        with open(self.index_path, "w", encoding="utf-8") as f:
            json.dump(self.items, f, ensure_ascii=False, indent=2)

    def list(self, sig_type=None):
        if sig_type is None:
            return list(self.items)
        return [it for it in self.items if it.get("type") == sig_type]

    def add(self, qimage: QImage, name: str, sig_type: str):
        """sig_type is 'signature' or 'initial'."""
        item_id = uuid.uuid4().hex[:12]
        filename = f"{item_id}.png"
        path = os.path.join(self.dir, filename)
        qimage.save(path, "PNG")
        item = {
            "id": item_id,
            "name": name or ("签名" if sig_type == "signature" else "缩写"),
            "type": sig_type,
            "file": filename,
        }
        self.items.append(item)
        self._save_index()
        return item

    def delete(self, item_id):
        item = next((it for it in self.items if it["id"] == item_id), None)
        if not item:
            return
        path = os.path.join(self.dir, item["file"])
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
        self.items = [it for it in self.items if it["id"] != item_id]
        self._save_index()

    def image_path(self, item):
        return os.path.join(self.dir, item["file"])

    def load_image(self, item) -> QImage:
        return QImage(self.image_path(item))
