"""HTTP server: JSON API + static web UI, behind a plaintext auth gate.

ThreadingHTTPServer with a single shared SQLite connection serialized by a
lock (fine for a single-user personal tool). Every /api/* route except
/api/login requires a valid token from the ``gym_token`` cookie.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import threading
import datetime as _dt
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Dict, Optional, Tuple
from urllib.parse import urlparse, parse_qs

from . import ai, auth, docs, feed, ingest, map_store, refresh, retrieval
from .db import bootstrap, connect, reindex_entry, utcnow

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".pdf": "application/pdf",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
}


class AppContext:
    """Shared, thread-safe application state."""

    def __init__(self, db_path: str, reports_dir: str, docs_dir: str,
                 default_model: Optional[str] = None):
        self.db_path = db_path
        self.reports_dir = reports_dir
        self.docs_dir = docs_dir
        self.default_model = default_model
        self.lock = threading.Lock()
        self.conn = connect(db_path)
        bootstrap(self.conn)

    def new_conn(self) -> sqlite3.Connection:
        return connect(self.db_path)


class Handler(BaseHTTPRequestHandler):
    ctx: AppContext = None  # set on the server instance subclass

    server_version = "Gymnasium/0.1"

    # -- low-level helpers --------------------------------------------------
    def log_message(self, fmt, *args):  # quieter logs
        sys.stderr.write("[server] " + (fmt % args) + "\n")

    def _cookies(self) -> SimpleCookie:
        c = SimpleCookie()
        raw = self.headers.get("Cookie")
        if raw:
            c.load(raw)
        return c

    def _token(self) -> Optional[str]:
        c = self._cookies()
        if "gym_token" in c:
            return c["gym_token"].value
        return None

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    def _send_json(self, obj, status: int = 200, headers: Optional[Dict[str, str]] = None):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if headers:
            for k, v in headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, data: bytes, content_type: str, status: int = 200,
                    download_name: Optional[str] = None, attachment: bool = False,
                    headers: Optional[Dict[str, str]] = None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if download_name:
            disposition = "attachment" if attachment else "inline"
            self.send_header("Content-Disposition",
                             '{}; filename="{}"'.format(disposition, download_name))
        if headers:
            for k, v in headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _unauthorized(self):
        self._send_json({"error": "unauthorized"}, status=401)

    # -- auth ---------------------------------------------------------------
    def _current_user(self) -> Optional[int]:
        with self.ctx.lock:
            return auth.verify_token(self.ctx.conn, self._token())

    # -- routing ------------------------------------------------------------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/"):
            return self._route_api("GET", path, parse_qs(parsed.query))
        return self._serve_static(path)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/"):
            return self._route_api("POST", path, parse_qs(parsed.query))
        self._send_json({"error": "not found"}, status=404)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/"):
            return self._route_api("DELETE", path, parse_qs(parsed.query))
        self._send_json({"error": "not found"}, status=404)

    # -- static -------------------------------------------------------------
    def _serve_file(self, abs_path: str, download_name: Optional[str] = None):
        if not os.path.isfile(abs_path):
            self._send_json({"error": "not found"}, status=404)
            return
        ext = os.path.splitext(abs_path)[1].lower()
        ctype = _CONTENT_TYPES.get(ext, "application/octet-stream")
        with open(abs_path, "rb") as fh:
            data = fh.read()
        self._send_bytes(data, ctype, download_name=download_name)

    def _serve_static(self, path: str):
        if path == "/" or path == "":
            # Login if unauthed, app shell if authed.
            user = self._current_user()
            target = "index.html" if user else "login.html"
            return self._serve_file(os.path.join(WEB_DIR, target))
        # Normalize and prevent path traversal.
        rel = path.lstrip("/")
        abs_path = os.path.normpath(os.path.join(WEB_DIR, rel))
        if not abs_path.startswith(WEB_DIR):
            self._send_json({"error": "forbidden"}, status=403)
            return
        self._serve_file(abs_path)

    # -- API dispatch -------------------------------------------------------
    def _route_api(self, method: str, path: str, query: Dict):
        # Public endpoint.
        if path == "/api/login" and method == "POST":
            return self._api_login()

        # Everything else needs auth.
        user_id = self._current_user()
        if user_id is None:
            return self._unauthorized()

        try:
            if path == "/api/logout" and method == "POST":
                return self._api_logout()
            if path == "/api/me" and method == "GET":
                return self._api_me(user_id)
            if path == "/api/models" and method == "GET":
                return self._api_models()
            if path == "/api/feed" and method == "GET":
                return self._api_feed(query)
            if path == "/api/items" and method == "POST":
                return self._api_items_create()
            if path == "/api/feed/facets" and method == "GET":
                return self._api_feed_facets(query)
            if path == "/api/summarize" and method == "POST":
                return self._api_summarize()
            if path == "/api/ask" and method == "POST":
                return self._api_ask()
            if path == "/api/chat" and method == "POST":
                return self._api_chat()
            if path == "/api/chat" and method == "GET":
                return self._api_chat_get(query)
            if path == "/api/kb" and method == "GET":
                return self._api_kb_list()
            if path == "/api/kb/search" and method == "GET":
                return self._api_kb_search(query)
            if path == "/api/kb/save" and method == "POST":
                return self._api_kb_save()
            if path == "/api/map" and method == "GET":
                return self._api_map()
            if path == "/api/map/edge" and method == "POST":
                return self._api_map_edge_add()
            if path == "/api/map/position" and method == "POST":
                return self._api_map_position()
            if path == "/api/map/ai-links" and method == "POST":
                return self._api_map_ai_links()
            if path == "/api/refresh" and method == "POST":
                return self._api_refresh()
            if path == "/api/refresh/status" and method == "GET":
                return self._api_refresh_status()

            # parameterized: /api/item/{id}, /api/item/{id}/document,
            # /api/kb/{id}, /api/map/edge/{id}
            parts = [p for p in path.split("/") if p]
            if len(parts) >= 3 and parts[0] == "api" and parts[1] == "item":
                if len(parts) == 3 and method == "GET":
                    return self._api_item(int(parts[2]))
                if len(parts) == 4 and parts[3] == "document" and method == "GET":
                    return self._api_item_document(int(parts[2]))
                if len(parts) == 4 and parts[3] == "markdown" and method == "GET":
                    return self._api_item_markdown_get(int(parts[2]))
                if len(parts) == 4 and parts[3] == "markdown" and method == "POST":
                    return self._api_item_markdown_post(int(parts[2]))
            if len(parts) == 3 and parts[0] == "api" and parts[1] == "kb" and method == "GET":
                return self._api_kb_get(int(parts[2]))
            if len(parts) == 4 and parts[:3] == ["api", "map", "edge"] and method == "DELETE":
                return self._api_map_edge_delete(int(parts[3]))
        except ValueError:
            return self._send_json({"error": "bad request"}, status=400)
        except ai.AIError as exc:
            return self._send_json({"error": str(exc)}, status=502)

        self._send_json({"error": "not found"}, status=404)

    # -- auth endpoints -----------------------------------------------------
    def _api_login(self):
        data = self._read_json()
        username = data.get("username", "")
        password = data.get("password", "")
        with self.ctx.lock:
            uid = auth.verify_credentials(self.ctx.conn, username, password)
            if uid is None:
                return self._send_json({"error": "invalid credentials"}, status=401)
            token = auth.issue_token(self.ctx.conn, uid)
        cookie = (
            "gym_token={}; Path=/; HttpOnly; SameSite=Lax; Max-Age={}".format(
                token, 30 * 24 * 3600)
        )
        self._send_json({"ok": True, "username": username}, headers={"Set-Cookie": cookie})

    def _api_logout(self):
        with self.ctx.lock:
            auth.revoke_token(self.ctx.conn, self._token())
        cookie = "gym_token=; Path=/; HttpOnly; Max-Age=0"
        self._send_json({"ok": True}, headers={"Set-Cookie": cookie})

    def _api_me(self, user_id: int):
        with self.ctx.lock:
            row = auth.get_user(self.ctx.conn, user_id)
        if row is None:
            return self._unauthorized()
        self._send_json({"id": row["id"], "username": row["username"]})

    # -- models -------------------------------------------------------------
    def _api_models(self):
        result = ai.list_models()
        result["default"] = self._default_model(result)
        self._send_json(result)

    def _default_model(self, listing: dict) -> Optional[str]:
        if self.ctx.default_model:
            return self.ctx.default_model
        providers = listing.get("providers") or []
        for g in providers:
            if g.get("models"):
                return g["models"][0]["id"]
        return None

    # -- feed / items -------------------------------------------------------
    def _item_dict(self, row: sqlite3.Row) -> dict:
        raw = feed.parse_raw(row)
        tag_list = (raw.get("labs_matched") or raw.get("topics") or [])[:3]
        if raw.get("language"):
            tag_list = [raw["language"]] + list(tag_list)
        out = {
            "id": row["id"],
            "kind": row["kind"],
            "title": row["title"],
            "source": row["source"],
            "url": row["url"],
            "abstract": row["abstract"],
            "why": row["why"],
            "signal": row["signal"],
            "published_at": row["published_at"],
            "summary_readable": json.loads(row["summary_readable"]) if row["summary_readable"] else None,
            "summary_terms": json.loads(row["summary_terms"]) if row["summary_terms"] else None,
            "doc_path": row["doc_path"],
            "has_markdown": bool(row["markdown_path"]),
            "markdown_source": row["markdown_source"],
            "added_by_user": bool(row["added_by_user"]),
            "tags": [t for t in tag_list if t][:3],
        }
        # Fields the cards / filters need (authors, company, publication, language).
        out.update(feed.item_facets(row, raw))
        return out

    def _api_feed(self, query: Dict):
        kind = (query.get("kind", [None])[0])
        limit = int(query.get("limit", ["50"])[0] or 50)
        q = (query.get("q", [""])[0] or "").strip()
        sort = (query.get("sort", ["recency"])[0] or "recency")
        added = (query.get("added", [None])[0] or "").strip().lower() in ("1", "true", "yes")
        filters = {
            "author": query.get("author", [None])[0],
            "company": query.get("company", [None])[0],
            "publication": query.get("publication", [None])[0],
            "language": query.get("language", [None])[0],
        }
        sql = "SELECT * FROM corpus_item"
        clauses = []
        params = []
        if kind in ("paper", "repo"):
            clauses.append("kind=?")
            params.append(kind)
        if added:
            # The "Added" view: only user-added items.
            clauses.append("COALESCE(added_by_user, 0) = 1")
        else:
            # The tracker feeds never surface user-added items.
            clauses.append("COALESCE(added_by_user, 0) = 0")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        with self.ctx.lock:
            rows = self.ctx.conn.execute(sql, params).fetchall()
        items = feed.select(rows, q=q, sort=sort, filters=filters, limit=limit)
        self._send_json({"items": [self._item_dict(r) for r in items]})

    def _api_items_create(self):
        """Create (or update) a user-added paper from a link.

        Deduped by ``external_id = url`` so re-adding the same link updates the
        existing row instead of duplicating it. The title is the provided one,
        else a best-effort page <title>/og:title, else the URL host. Opening it
        later works like any article (ensure_document + auto-conversion handle
        an arbitrary URL).
        """
        data = self._read_json()
        url = (data.get("url") or "").strip()
        if not url:
            return self._send_json({"error": "url required"}, status=400)
        title = (data.get("title") or "").strip()
        if not title:
            title = _page_title(url) or _url_host(url) or url
        now = utcnow()
        with self.ctx.lock:
            existing = self.ctx.conn.execute(
                "SELECT id FROM corpus_item WHERE kind='paper' AND external_id=?",
                (url,)).fetchone()
            if existing is not None:
                item_id = int(existing["id"])
                self.ctx.conn.execute(
                    "UPDATE corpus_item SET title=?, url=?, source=?, "
                    "added_by_user=1, published_at=?, ingested_at=? WHERE id=?",
                    (title, url, "Added by you", now, now, item_id))
            else:
                cur = self.ctx.conn.execute(
                    "INSERT INTO corpus_item (kind, external_id, title, source, url, "
                    "signal, added_by_user, published_at, ingested_at) "
                    "VALUES ('paper', ?, ?, 'Added by you', ?, 0, 1, ?, ?)",
                    (url, title, url, now, now))
                item_id = int(cur.lastrowid)
            self.ctx.conn.commit()
        self._send_json({"ok": True, "id": item_id})

    def _api_feed_facets(self, query: Dict):
        kind = (query.get("kind", ["paper"])[0]) or "paper"
        if kind not in ("paper", "repo"):
            return self._send_json({"error": "bad kind"}, status=400)
        with self.ctx.lock:
            rows = self.ctx.conn.execute(
                "SELECT * FROM corpus_item WHERE kind=?", (kind,)).fetchall()
        self._send_json(feed.facets(rows, kind))

    def _api_item(self, item_id: int):
        with self.ctx.lock:
            row = self.ctx.conn.execute(
                "SELECT * FROM corpus_item WHERE id=?", (item_id,)).fetchone()
            if row is None:
                return self._send_json({"error": "not found"}, status=404)
            # Ensure the original document is fetched to disk.
            docs.ensure_document(row, self.ctx.docs_dir, self.ctx.conn)
            row = self.ctx.conn.execute(
                "SELECT * FROM corpus_item WHERE id=?", (item_id,)).fetchone()
            out = self._item_dict(row)
            # Cheap advertisement only: a user markdown exists, OR a real source
            # document is on disk that could be converted on first read. No
            # conversion runs here — that happens lazily in the markdown GET.
            out["markdown_available"] = bool(row["markdown_path"]) or \
                docs.has_convertible_source(row, self.ctx.docs_dir) or \
                docs.has_repo_readme(row, self.ctx.docs_dir)
        self._send_json(out)

    def _api_item_document(self, item_id: int):
        with self.ctx.lock:
            row = self.ctx.conn.execute(
                "SELECT * FROM corpus_item WHERE id=?", (item_id,)).fetchone()
            if row is None:
                return self._send_json({"error": "not found"}, status=404)
            doc_path = row["doc_path"]
            if not doc_path:
                doc_path = docs.ensure_document(row, self.ctx.docs_dir, self.ctx.conn)
        if not doc_path:
            return self._send_json({"error": "no document"}, status=404)
        abs_path = os.path.normpath(os.path.join(self.ctx.docs_dir, doc_path))
        docs_root = os.path.abspath(self.ctx.docs_dir)
        if not os.path.abspath(abs_path).startswith(docs_root):
            return self._send_json({"error": "forbidden"}, status=403)
        if not os.path.isfile(abs_path):
            return self._send_json({"error": "not found"}, status=404)
        name = os.path.basename(abs_path)
        ext = os.path.splitext(abs_path)[1].lower()
        with open(abs_path, "rb") as fh:
            data = fh.read()
        if ext in (".html", ".htm"):
            # Stored upstream HTML must never run inline on our origin (it would
            # execute same-origin with the authenticated API — stored XSS). Serve
            # it as a non-executing attachment instead.
            self._send_bytes(data, "text/plain; charset=utf-8",
                             download_name=name, attachment=True)
        else:
            ctype = _CONTENT_TYPES.get(ext, "application/octet-stream")
            self._send_bytes(data, ctype, download_name=name)

    # -- markdown attachment ------------------------------------------------
    def _api_item_markdown_get(self, item_id: int):
        with self.ctx.lock:
            row = self.ctx.conn.execute(
                "SELECT * FROM corpus_item WHERE id=?", (item_id,)).fetchone()
            if row is None:
                return self._send_json({"error": "not found"}, status=404)
            # Precedence: a user upload always wins over the auto version.
            content = docs.read_markdown(row, self.ctx.docs_dir)
            source = "user" if content is not None else None
            if content is None and row["kind"] == "repo":
                # A repo's README.md is already Markdown — serve it directly.
                # Ensure it's on disk first, then re-read the (possibly updated) row.
                docs.ensure_document(row, self.ctx.docs_dir, self.ctx.conn)
                row = self.ctx.conn.execute(
                    "SELECT * FROM corpus_item WHERE id=?", (item_id,)).fetchone()
                content = docs.read_repo_readme(row, self.ctx.docs_dir)
                if content is not None:
                    source = "readme"
            if content is None and row["kind"] != "repo":
                # Already-cached auto conversion, if any.
                content = docs.read_auto_markdown(row, self.ctx.docs_dir)
                if content is not None and docs.auto_markdown_is_stale(row, content):
                    # Legacy cache with relative image URLs that 404 in the
                    # reader — regenerate it once with absolute URLs.
                    regenerated = docs.auto_markdown(row, self.ctx.docs_dir, self.ctx.conn)
                    if regenerated is not None:
                        content = regenerated
                if content is None:
                    # Lazy first conversion: convert the stored original once.
                    content = docs.auto_markdown(row, self.ctx.docs_dir, self.ctx.conn)
                    if content is not None:
                        self.ctx.conn.execute(
                            "UPDATE corpus_item SET markdown_source=? WHERE id=?",
                            ("auto", item_id))
                        self.ctx.conn.commit()
                if content is not None:
                    source = "auto"
        if content is None:
            return self._send_json({"error": "no markdown"}, status=404)
        self._send_bytes(content.encode("utf-8"), "text/markdown; charset=utf-8",
                         headers={"X-Markdown-Source": source})

    def _api_item_markdown_post(self, item_id: int):
        with self.ctx.lock:
            row = self.ctx.conn.execute(
                "SELECT * FROM corpus_item WHERE id=?", (item_id,)).fetchone()
        if row is None:
            return self._send_json({"error": "not found"}, status=404)
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return self._send_json({"error": "empty body"}, status=400)
        if length > _MAX_MARKDOWN:
            return self._send_json({"error": "too large"}, status=413)
        raw = self.rfile.read(length)
        ctype = (self.headers.get("Content-Type") or "").lower()
        if "multipart/form-data" in ctype:
            data = _parse_multipart_file(raw, ctype)
            if data is None:
                return self._send_json({"error": "no file field"}, status=400)
        else:
            data = raw
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError:
            return self._send_json({"error": "invalid encoding"}, status=400)
        rel = docs.save_markdown(row, content, self.ctx.docs_dir)
        with self.ctx.lock:
            # An upload always overrides any auto version (source=user).
            self.ctx.conn.execute(
                "UPDATE corpus_item SET markdown_path=?, markdown_source=? WHERE id=?",
                (rel, "user", item_id))
            self.ctx.conn.commit()
        self._send_json({"ok": True, "has_markdown": True})

    # -- summarize ----------------------------------------------------------
    def _api_summarize(self):
        data = self._read_json()
        item_id = int(data.get("item_id"))
        model = data.get("model") or self.ctx.default_model
        with self.ctx.lock:
            row = self.ctx.conn.execute(
                "SELECT * FROM corpus_item WHERE id=?", (item_id,)).fetchone()
        if row is None:
            return self._send_json({"error": "not found"}, status=404)
        item = self._item_dict(row)
        # Summarize once and cache; reuse the cached summary thereafter.
        cached = item["summary_readable"]
        if not cached:
            result = ai.summarize_item(item, model)
            with self.ctx.lock:
                self.ctx.conn.execute(
                    "UPDATE corpus_item SET summary_readable=?, summary_terms=? WHERE id=?",
                    (json.dumps(result["summary"]), json.dumps(result["terms"]), item_id),
                )
                self.ctx.conn.commit()
            summary, terms = result["summary"], result["terms"]
        else:
            summary, terms = cached, item["summary_terms"] or []
        self._send_json({"summary": summary, "terms": terms, "model": model})

    # -- ask ----------------------------------------------------------------
    def _api_ask(self):
        data = self._read_json()
        span = data.get("span_text", "")
        mode = data.get("mode", "explain")
        model = data.get("model") or self.ctx.default_model
        item_id = data.get("item_id")
        kb_entry_id = data.get("kb_entry_id")
        message = data.get("message")  # follow-up question text, if any

        item = {}
        if item_id:
            with self.ctx.lock:
                row = self.ctx.conn.execute(
                    "SELECT * FROM corpus_item WHERE id=?", (int(item_id),)).fetchone()
            if row is not None:
                item = self._item_dict(row)

        history = []
        if kb_entry_id:
            with self.ctx.lock:
                rows = self.ctx.conn.execute(
                    "SELECT role, content FROM kb_message WHERE kb_entry_id=? ORDER BY id",
                    (int(kb_entry_id),)).fetchall()
            history = [{"role": r["role"], "content": r["content"]} for r in rows]

        # When it's a follow-up question, the question itself is the prompt.
        ask_span = message if (mode == "ask" and message) else span
        # Ground the answer in the reader's own KB notes / concept map. The
        # query is whatever the reader is asking about (the question or span).
        kb_notes = None
        graph = None
        if item:
            with self.ctx.lock:
                bundle = retrieval.retrieve_context(self.ctx.conn, item, ask_span)
            kb_notes = bundle["notes"]
            graph = {"concepts": bundle["concepts"], "edges": bundle["edges"]}
        answer = ai.explain(ask_span, mode, item, model, history=history,
                            kb_notes=kb_notes, graph=graph)

        # If tied to a saved entry, append the user turn + answer.
        if kb_entry_id:
            now = utcnow()
            answer_text = self._answer_text(answer)
            with self.ctx.lock:
                if message:
                    self.ctx.conn.execute(
                        "INSERT INTO kb_message (kb_entry_id, role, content, created_at) "
                        "VALUES (?,?,?,?)", (int(kb_entry_id), "user", message, now))
                self.ctx.conn.execute(
                    "INSERT INTO kb_message (kb_entry_id, role, content, created_at) "
                    "VALUES (?,?,?,?)", (int(kb_entry_id), "assistant", answer_text, now))
                reindex_entry(self.ctx.conn, int(kb_entry_id))
                self.ctx.conn.commit()
        self._send_json({"answer": answer, "model": model})

    @staticmethod
    def _answer_text(answer: dict) -> str:
        parts = [answer.get("lead", ""), answer.get("body", "")]
        if answer.get("analogy"):
            parts.append("Picture it: " + answer["analogy"])
        return "\n".join(p for p in parts if p)

    # -- article chat -------------------------------------------------------
    def _chat_entry_id(self, item_id: int, title: str, create: bool = True):
        """Return the single persistent chat kb_entry id for an article.

        One thread per item, marked mode='chat'. Created on demand (under the
        caller's lock) when ``create`` is set.
        """
        row = self.ctx.conn.execute(
            "SELECT id FROM kb_entry WHERE item_id=? AND mode='chat' ORDER BY id LIMIT 1",
            (int(item_id),)).fetchone()
        if row is not None:
            return int(row["id"])
        if not create:
            return None
        term = _term_from_span(title) or "Article chat"
        irow = self.ctx.conn.execute(
            "SELECT url FROM corpus_item WHERE id=?", (int(item_id),)).fetchone()
        source_url = irow["url"] if irow else None
        cur = self.ctx.conn.execute(
            "INSERT INTO kb_entry (term, span_text, item_id, source_url, mode, "
            "tag, created_at) VALUES (?,?,?,?,?,?,?)",
            (term, title or term, int(item_id), source_url, "chat", "chat", utcnow()))
        self.ctx.conn.commit()
        return int(cur.lastrowid)

    def _api_chat_get(self, query: Dict):
        item_id = query.get("item_id", [None])[0]
        if not item_id:
            return self._send_json({"error": "item_id required"}, status=400)
        with self.ctx.lock:
            entry_id = self._chat_entry_id(int(item_id), "", create=False)
            messages = []
            if entry_id is not None:
                rows = self.ctx.conn.execute(
                    "SELECT role, content, created_at FROM kb_message "
                    "WHERE kb_entry_id=? ORDER BY id", (entry_id,)).fetchall()
                messages = [
                    {"role": r["role"], "content": r["content"], "created_at": r["created_at"]}
                    for r in rows
                ]
        self._send_json({"item_id": int(item_id), "kb_entry_id": entry_id,
                         "messages": messages})

    def _api_chat(self):
        data = self._read_json()
        item_id = data.get("item_id")
        message = (data.get("message") or "").strip()
        model = data.get("model") or self.ctx.default_model
        if not item_id or not message:
            return self._send_json({"error": "item_id and message required"}, status=400)

        with self.ctx.lock:
            row = self.ctx.conn.execute(
                "SELECT * FROM corpus_item WHERE id=?", (int(item_id),)).fetchone()
            if row is None:
                return self._send_json({"error": "not found"}, status=404)
            item = self._item_dict(row)
            entry_id = self._chat_entry_id(int(item_id), item.get("title") or "")
            hist_rows = self.ctx.conn.execute(
                "SELECT role, content FROM kb_message WHERE kb_entry_id=? ORDER BY id",
                (entry_id,)).fetchall()
            history = [{"role": r["role"], "content": r["content"]} for r in hist_rows]
            bundle = retrieval.retrieve_context(self.ctx.conn, item, message)

        graph = {"concepts": bundle["concepts"], "edges": bundle["edges"]}
        answer = ai.chat(item, history, message, kb_notes=bundle["notes"],
                         graph=graph, excerpt=bundle["excerpt"], model=model)

        now = utcnow()
        answer_text = self._answer_text(answer)
        with self.ctx.lock:
            self.ctx.conn.execute(
                "INSERT INTO kb_message (kb_entry_id, role, content, created_at) "
                "VALUES (?,?,?,?)", (entry_id, "user", message, now))
            self.ctx.conn.execute(
                "INSERT INTO kb_message (kb_entry_id, role, content, created_at) "
                "VALUES (?,?,?,?)", (entry_id, "assistant", answer_text, now))
            reindex_entry(self.ctx.conn, entry_id)
            self.ctx.conn.commit()
        self._send_json({
            "answer": answer,
            "model": model,
            "kb_entry_id": entry_id,
            "grounded": bundle["grounded"],
        })

    # -- knowledge base -----------------------------------------------------
    def _entry_dict(self, row: sqlite3.Row, with_messages: bool = False) -> dict:
        out = {
            "id": row["id"],
            "term": row["term"],
            "span_text": row["span_text"],
            "item_id": row["item_id"],
            "source_url": row["source_url"],
            "source_doc_path": row["source_doc_path"],
            "mode": row["mode"],
            "model": row["model"],
            "lead": row["lead"],
            "body": row["body"],
            "analogy": row["analogy"],
            "tag": row["tag"],
            "created_at": row["created_at"],
        }
        # Source title for the "From:" link.
        if row["item_id"]:
            irow = self.ctx.conn.execute(
                "SELECT title FROM corpus_item WHERE id=?", (row["item_id"],)).fetchone()
            out["source_title"] = irow["title"] if irow else None
        if with_messages:
            mrows = self.ctx.conn.execute(
                "SELECT role, content, created_at FROM kb_message WHERE kb_entry_id=? ORDER BY id",
                (row["id"],)).fetchall()
            out["messages"] = [
                {"role": m["role"], "content": m["content"], "created_at": m["created_at"]}
                for m in mrows
            ]
        return out

    def _api_kb_list(self):
        with self.ctx.lock:
            rows = self.ctx.conn.execute(
                "SELECT * FROM kb_entry ORDER BY id DESC").fetchall()
            out = [self._entry_dict(r) for r in rows]
        self._send_json({"entries": out})

    def _api_kb_get(self, entry_id: int):
        with self.ctx.lock:
            row = self.ctx.conn.execute(
                "SELECT * FROM kb_entry WHERE id=?", (entry_id,)).fetchone()
            if row is None:
                return self._send_json({"error": "not found"}, status=404)
            out = self._entry_dict(row, with_messages=True)
        self._send_json(out)

    def _api_kb_search(self, query: Dict):
        q = (query.get("q", [""])[0] or "").strip()
        if not q:
            return self._api_kb_list()
        # Build a safe FTS match: OR the tokens, prefix-match each.
        tokens = [t for t in _fts_tokens(q)]
        if not tokens:
            return self._send_json({"entries": []})
        match = " OR ".join('"{}"*'.format(t) for t in tokens)
        with self.ctx.lock:
            try:
                rows = self.ctx.conn.execute(
                    "SELECT e.* FROM kb_fts f JOIN kb_entry e ON e.id=f.entry_id "
                    "WHERE kb_fts MATCH ? ORDER BY rank", (match,)).fetchall()
            except sqlite3.OperationalError:
                rows = []
            out = [self._entry_dict(r) for r in rows]
        self._send_json({"entries": out})

    def _api_kb_save(self):
        data = self._read_json()
        span = data.get("span_text", "")
        item_id = data.get("item_id")
        mode = data.get("mode", "explain")
        model = data.get("model")
        answer = data.get("answer") or {}
        thread = data.get("thread") or []  # [{role, content}, ...] follow-ups

        term = _term_from_span(span)
        lead = answer.get("lead", "")
        body = answer.get("body", "")
        analogy = answer.get("analogy")
        source_url = None
        source_doc_path = None
        tag = None

        with self.ctx.lock:
            irow = None
            if item_id:
                irow = self.ctx.conn.execute(
                    "SELECT * FROM corpus_item WHERE id=?", (int(item_id),)).fetchone()
            if irow is not None:
                source_url = irow["url"]
                # Ensure the source document is on disk and snapshot its path.
                source_doc_path = docs.ensure_document(irow, self.ctx.docs_dir, self.ctx.conn)
                try:
                    raw = json.loads(irow["raw_json"]) if irow["raw_json"] else {}
                except (ValueError, TypeError):
                    raw = {}
                tag = (raw.get("labs_matched") or raw.get("topics") or [None])[0]
                if not tag and raw.get("primary_field"):
                    tag = raw["primary_field"]
            now = utcnow()
            cur = self.ctx.conn.execute(
                "INSERT INTO kb_entry (term, span_text, item_id, source_url, "
                "source_doc_path, mode, model, lead, body, analogy, tag, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (term, span, int(item_id) if item_id else None, source_url,
                 source_doc_path, mode, model, lead, body, analogy,
                 tag or "note", now),
            )
            entry_id = int(cur.lastrowid)

            # Persist the WHOLE conversation: the initial answer, then each
            # follow-up turn passed in `thread`.
            self.ctx.conn.execute(
                "INSERT INTO kb_message (kb_entry_id, role, content, created_at) "
                "VALUES (?,?,?,?)", (entry_id, "assistant", self._answer_text(answer), now))
            for turn in thread:
                role = "user" if turn.get("role") in ("user", "q") else "assistant"
                content = turn.get("content") or turn.get("text") or ""
                if content:
                    self.ctx.conn.execute(
                        "INSERT INTO kb_message (kb_entry_id, role, content, created_at) "
                        "VALUES (?,?,?,?)", (entry_id, role, content, now))
            reindex_entry(self.ctx.conn, entry_id)
            # A saved entry becomes a knowledge-map node.
            map_store.ensure_concept_for_entry(self.ctx.conn, entry_id)
            self.ctx.conn.commit()
            row = self.ctx.conn.execute(
                "SELECT * FROM kb_entry WHERE id=?", (entry_id,)).fetchone()
            out = self._entry_dict(row, with_messages=True)
        self._send_json({"ok": True, "entry": out})

    # -- map ----------------------------------------------------------------
    def _api_map(self):
        with self.ctx.lock:
            data = map_store.get_map(self.ctx.conn)
        self._send_json(data)

    def _api_map_edge_add(self):
        data = self._read_json()
        src = int(data.get("src"))
        dst = int(data.get("dst"))
        with self.ctx.lock:
            edge_id = map_store.add_edge(self.ctx.conn, src, dst, source="manual")
        if edge_id is None:
            return self._send_json({"error": "invalid edge"}, status=400)
        self._send_json({"ok": True, "id": edge_id})

    def _api_map_edge_delete(self, edge_id: int):
        with self.ctx.lock:
            map_store.delete_edge(self.ctx.conn, edge_id)
        self._send_json({"ok": True})

    def _api_map_position(self):
        data = self._read_json()
        concept_id = int(data.get("concept_id"))
        with self.ctx.lock:
            map_store.set_position(self.ctx.conn, concept_id,
                                   float(data.get("x")), float(data.get("y")))
        self._send_json({"ok": True})

    def _api_map_ai_links(self):
        data = self._read_json()
        model = data.get("model") or self.ctx.default_model
        with self.ctx.lock:
            result = map_store.ai_links(self.ctx.conn, model)
        self._send_json(result)

    # -- refresh ------------------------------------------------------------
    def _api_refresh(self):
        data = self._read_json()
        kind = data.get("kind")
        days = int(data.get("days") or 7)
        state = refresh.run_refresh(kind, days, self.ctx.reports_dir, self.ctx.new_conn)
        self._send_json(state)

    def _api_refresh_status(self):
        self._send_json(refresh.status())


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
import re as _re

_MAX_MARKDOWN = 2 * 1024 * 1024  # 2 MB cap on attached markdown


def _parse_multipart_file(raw: bytes, ctype: str) -> Optional[bytes]:
    """Extract the single uploaded file's bytes from a multipart/form-data body.

    Minimal stdlib-only parse: enough for one file field. Returns None when no
    form-data part is found.
    """
    m = _re.search(r'boundary="?([^";]+)"?', ctype)
    if not m:
        return None
    delim = b"--" + m.group(1).encode()
    fallback = None
    for part in raw.split(delim):
        if b"Content-Disposition" not in part:
            continue
        header_blob, sep, body = part.partition(b"\r\n\r\n")
        if not sep:
            continue
        if body.endswith(b"\r\n"):
            body = body[:-2]
        if b"filename=" in header_blob:
            return body  # prefer the actual file field
        if fallback is None:
            fallback = body
    return fallback


def _url_host(url: str) -> str:
    """The host of a URL, used as a last-resort title for an added article."""
    try:
        return urlparse(url).netloc or ""
    except ValueError:
        return ""


def _page_title(url: str) -> Optional[str]:
    """Best-effort <title>/og:title for an added link. Non-fatal; None on failure.

    Reuses ``docs._fetch`` (bounded timeout, never raises) so a slow or down
    page can't block adding the article — the caller falls back to the host.
    """
    data = docs._fetch(url)
    if not data:
        return None
    try:
        html = data.decode("utf-8", "ignore")
    except Exception:
        return None
    m = _re.search(
        r'<meta[^>]+(?:property|name)=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
        html, _re.IGNORECASE)
    if not m:
        m = _re.search(
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']og:title["\']',
            html, _re.IGNORECASE)
    if m:
        return _re.sub(r"\s+", " ", m.group(1)).strip() or None
    m = _re.search(r"<title[^>]*>(.*?)</title>", html, _re.IGNORECASE | _re.DOTALL)
    if m:
        return _re.sub(r"\s+", " ", m.group(1)).strip() or None
    return None


def _fts_tokens(q: str):
    return [t for t in _re.findall(r"[A-Za-z0-9]+", q.lower()) if t]


def _term_from_span(span: str) -> str:
    term = _re.sub(r"\s+", " ", span or "").strip()
    if len(term) > 42:
        term = term[:42].strip() + "…"
    if term:
        term = term[0].upper() + term[1:]
    return term or "Note"


# --------------------------------------------------------------------------
# Server bootstrap & CLI
# --------------------------------------------------------------------------
def make_server(host: str, port: int, ctx: AppContext) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"ctx": ctx})
    return ThreadingHTTPServer((host, port), handler)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # Console subcommand: gymnasium adduser <username> <password>
    if argv and argv[0] == "adduser":
        return _cmd_adduser(argv[1:])

    parser = argparse.ArgumentParser(
        prog="gymnasium", description="Gymnasium University server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8077)
    parser.add_argument("--db", default="data/gymnasium.db")
    parser.add_argument("--reports", default="reports")
    parser.add_argument("--docs-dir", default="data/documents")
    parser.add_argument("--model", default=os.environ.get("GYM_MODEL"),
                        help="default AI model id (else first listed)")
    parser.add_argument("--ingest-on-start", action="store_true",
                        help="ingest the latest report sidecars before serving")
    args = parser.parse_args(argv)

    ctx = AppContext(args.db, args.reports, args.docs_dir, default_model=args.model)
    if args.ingest_on_start:
        counts = ingest.ingest_latest(args.reports, ctx.conn)
        print("[server] ingested:", counts)

    httpd = make_server(args.host, args.port, ctx)
    print("[server] Gymnasium University on http://{}:{}".format(args.host, args.port))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[server] shutting down")
    finally:
        httpd.server_close()
    return 0


def _cmd_adduser(argv) -> int:
    parser = argparse.ArgumentParser(prog="gymnasium adduser")
    parser.add_argument("username")
    parser.add_argument("password")
    parser.add_argument("--db", default="data/gymnasium.db")
    args = parser.parse_args(argv)

    conn = connect(args.db)
    bootstrap(conn)
    try:
        uid = auth.add_user(conn, args.username, args.password)
    except ValueError as exc:
        print("error:", exc, file=sys.stderr)
        return 2
    except sqlite3.IntegrityError:
        print("error: user '{}' already exists".format(args.username), file=sys.stderr)
        return 2
    print("created user '{}' (id {})".format(args.username, uid))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
