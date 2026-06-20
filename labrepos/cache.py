"""A tiny on-disk JSON cache, namespaced by topic.

Keeps repeated runs cheap and polite: GitHub org/user repo listings and
per-repo metadata are stable enough to cache between runs.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Optional


class Cache:
    def __init__(self, cache_dir: Optional[str], enabled: bool = True) -> None:
        self.cache_dir = cache_dir
        self.enabled = enabled and bool(cache_dir)

    def _path(self, namespace: str, key: str) -> str:
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
        return os.path.join(self.cache_dir, namespace, digest + ".json")

    def get(self, namespace: str, key: str) -> Optional[Any]:
        if not self.enabled:
            return None
        path = self._path(namespace, key)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

    def set(self, namespace: str, key: str, value: Any) -> None:
        if not self.enabled:
            return
        path = self._path(namespace, key)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(value, fh)
        except OSError:
            # Caching is best-effort; never fail the run over a cache write.
            pass
