"""Offline, fixture-based tests for the university package.

No live network: AI is stubbed via a fake `opencode` binary (OPENCODE_BIN),
document downloads are monkeypatched, and the tracker pipeline is stubbed.
"""

import json
import os
import sqlite3
import sys
import threading
import time
import types

import pytest

from university import ai, auth, db, docs, ingest, map_store, refresh

FAKE_OPENCODE = os.path.join(os.path.dirname(__file__), "fixtures", "fake_opencode.py")


def _install_fake_markitdown(monkeypatch, text="# Auto\n\nConverted body."):
    """Inject an offline stand-in for ``markitdown`` so no binary/network runs.

    ``docs.auto_markdown`` does ``from markitdown import MarkItDown`` at call
    time, so swapping the module in ``sys.modules`` is enough to control it.
    """
    mod = types.ModuleType("markitdown")

    class _Result:
        def __init__(self, t):
            self.text_content = t

    class MarkItDown:
        def convert(self, path):
            return _Result(text)

    mod.MarkItDown = MarkItDown
    monkeypatch.setitem(sys.modules, "markitdown", mod)
    return text


@pytest.fixture(autouse=True)
def _fake_ai(monkeypatch):
    monkeypatch.setenv("OPENCODE_BIN", FAKE_OPENCODE)
    yield


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    db.bootstrap(c)
    return c


@pytest.fixture
def sample_reports(tmp_path):
    """A tiny reports dir with one paper sidecar and one repo sidecar."""
    papers = {
        "papers": [
            {"title": "Mixture-of-Experts at Scale", "arxiv_id": "2601.00001",
             "date": "2026-06-10", "abstract": "A study of routing in MoE models.",
             "abs_url": "https://arxiv.org/abs/2601.00001",
             "pdf_url": "https://arxiv.org/pdf/2601.00001",
             "max_author_cited_by": 40000, "labs_matched": ["google"],
             "primary_field": "Computer Science",
             "impact_summary": "max author citations 40000"},
            {"title": "Tiny Result", "arxiv_id": "2601.00002", "date": "2026-06-01",
             "abstract": "A small note.", "max_author_cited_by": 10,
             "labs_matched": ["openai"]},
        ]
    }
    repos = {
        "repos": [
            {"full_name": "acme/agent-forge", "owner": "acme", "name": "agent-forge",
             "description": "An autonomous PR pipeline.",
             "html_url": "https://github.com/acme/agent-forge", "language": "Python",
             "stargazers_count": 9000, "created_at": "2026-06-05T00:00:00Z",
             "topics": ["agents"]},
        ]
    }
    rp = tmp_path / "reports"
    rp.mkdir()
    (rp / "labpapers_2026-06-10_30d.json").write_text(json.dumps(papers))
    (rp / "labrepos_2026-06-05_30d.json").write_text(json.dumps(repos))
    return str(rp)


# --------------------------------------------------------------------------
# auth
# --------------------------------------------------------------------------
class _CountingConn:
    """Wraps a sqlite3 connection and counts execute() calls."""
    def __init__(self, inner):
        self._inner = inner
        self.execute_calls = 0

    def execute(self, *a, **k):
        self.execute_calls += 1
        return self._inner.execute(*a, **k)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def test_alnum_guard_rejects_before_db(conn):
    # If the guard runs first, the DB is never queried for a bad credential.
    auth.add_user(conn, "maya", "secret1")
    spy = _CountingConn(conn)
    assert auth.verify_credentials(spy, "ma!ya", "secret1") is None
    assert spy.execute_calls == 0  # guard short-circuited before any query
    # a well-formed but wrong credential DOES hit the DB
    assert auth.verify_credentials(spy, "maya", "wrong") is None
    assert spy.execute_calls == 1


def test_password_right_and_wrong(conn):
    uid = auth.add_user(conn, "maya", "pw123")
    assert auth.verify_credentials(conn, "maya", "pw123") == uid
    assert auth.verify_credentials(conn, "maya", "nope") is None


def test_token_issue_reuse_slide_expire_revoke(conn):
    uid = auth.add_user(conn, "maya", "pw123")
    tok = auth.issue_token(conn, uid)
    assert auth.verify_token(conn, tok) == uid
    # expire it manually
    conn.execute("UPDATE auth_token SET expires_at=? WHERE token=?",
                 ("2000-01-01T00:00:00", tok))
    conn.commit()
    assert auth.verify_token(conn, tok) is None
    # revoke
    tok2 = auth.issue_token(conn, uid)
    auth.revoke_token(conn, tok2)
    assert auth.verify_token(conn, tok2) is None


def test_adduser_rejects_nonalnum(conn):
    with pytest.raises(ValueError):
        auth.add_user(conn, "ma ya", "pw")


# --------------------------------------------------------------------------
# bootstrap / fts
# --------------------------------------------------------------------------
def test_bootstrap_idempotent(conn):
    db.bootstrap(conn)  # second call must not raise
    db.bootstrap(conn)
    tables = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table')").fetchall()}
    assert {"users", "corpus_item", "kb_entry", "kb_message", "concept",
            "concept_edge"}.issubset(tables)


def test_bootstrap_adds_markdown_column_on_old_schema():
    """An existing DB whose corpus_item predates markdown_path is migrated."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    # Pre-existing OLD schema: corpus_item WITHOUT markdown_path.
    c.executescript(
        "CREATE TABLE corpus_item ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  kind TEXT NOT NULL, external_id TEXT NOT NULL, title TEXT NOT NULL,"
        "  ingested_at TEXT NOT NULL, raw_json TEXT,"
        "  UNIQUE (kind, external_id));"
    )
    cols = {r["name"] for r in c.execute("PRAGMA table_info(corpus_item)").fetchall()}
    assert "markdown_path" not in cols
    db.bootstrap(c)
    cols = {r["name"] for r in c.execute("PRAGMA table_info(corpus_item)").fetchall()}
    assert "markdown_path" in cols
    db.bootstrap(c)  # idempotent re-run on the migrated DB must not raise


# --------------------------------------------------------------------------
# ingest
# --------------------------------------------------------------------------
def test_ingest_loads_and_normalizes(conn, sample_reports):
    counts = ingest.ingest_reports(sample_reports, conn)
    assert counts["new"] == 3
    rows = conn.execute("SELECT signal FROM corpus_item").fetchall()
    assert all(0 <= r["signal"] <= 100 for r in rows)
    assert conn.execute("SELECT COUNT(*) c FROM corpus_item").fetchone()["c"] == 3


def test_ingest_dedupes_on_rerun(conn, sample_reports):
    ingest.ingest_reports(sample_reports, conn)
    before = conn.execute("SELECT COUNT(*) c FROM corpus_item").fetchone()["c"]
    ingest.ingest_reports(sample_reports, conn)
    after = conn.execute("SELECT COUNT(*) c FROM corpus_item").fetchone()["c"]
    assert before == after == 3


# --------------------------------------------------------------------------
# docs
# --------------------------------------------------------------------------
def test_ensure_document_stores_paper_and_repo(conn, sample_reports, tmp_path, monkeypatch):
    monkeypatch.setattr(docs, "_fetch", lambda url: b"FAKEDOC")
    ingest.ingest_reports(sample_reports, conn)
    docs_dir = str(tmp_path / "documents")
    paper = conn.execute("SELECT * FROM corpus_item WHERE kind='paper' LIMIT 1").fetchone()
    rel = docs.ensure_document(paper, docs_dir, conn)
    assert rel.startswith("papers/")
    assert os.path.isfile(os.path.join(docs_dir, rel))
    # doc_path persisted
    refreshed = conn.execute("SELECT doc_path FROM corpus_item WHERE id=?", (paper["id"],)).fetchone()
    assert refreshed["doc_path"] == rel
    repo = conn.execute("SELECT * FROM corpus_item WHERE kind='repo' LIMIT 1").fetchone()
    rrel = docs.ensure_document(repo, docs_dir, conn)
    assert rrel.startswith("repos/") and os.path.isfile(os.path.join(docs_dir, rrel))


def test_ensure_document_idempotent_and_failsafe(conn, sample_reports, tmp_path, monkeypatch):
    monkeypatch.setattr(docs, "_fetch", lambda url: None)  # every download fails
    ingest.ingest_reports(sample_reports, conn)
    docs_dir = str(tmp_path / "documents")
    paper = conn.execute("SELECT * FROM corpus_item WHERE kind='paper' LIMIT 1").fetchone()
    rel = docs.ensure_document(paper, docs_dir, conn)  # must not raise
    assert rel is not None  # falls back to abstract.txt
    again = conn.execute("SELECT * FROM corpus_item WHERE id=?", (paper["id"],)).fetchone()
    assert docs.ensure_document(again, docs_dir, conn) == rel  # idempotent


def test_save_and_read_markdown(conn, sample_reports, tmp_path):
    ingest.ingest_reports(sample_reports, conn)
    docs_dir = str(tmp_path / "documents")
    paper = conn.execute("SELECT * FROM corpus_item WHERE kind='paper' LIMIT 1").fetchone()
    rel = docs.save_markdown(paper, "# Title\n\nBody.", docs_dir)
    assert rel.startswith("papers/") and rel.endswith("article.md")
    assert os.path.isfile(os.path.join(docs_dir, rel))
    # read_markdown follows markdown_path on the row.
    conn.execute("UPDATE corpus_item SET markdown_path=? WHERE id=?", (rel, paper["id"]))
    conn.commit()
    paper = conn.execute("SELECT * FROM corpus_item WHERE id=?", (paper["id"],)).fetchone()
    assert docs.read_markdown(paper, docs_dir) == "# Title\n\nBody."
    # Overwrite is idempotent on the path and replaces the content.
    rel2 = docs.save_markdown(paper, "# New", docs_dir)
    assert rel2 == rel
    assert docs.read_markdown(paper, docs_dir) == "# New"
    # No attachment -> None.
    repo = conn.execute("SELECT * FROM corpus_item WHERE kind='repo' LIMIT 1").fetchone()
    assert docs.read_markdown(repo, docs_dir) is None


def test_auto_markdown_converts_and_caches(conn, sample_reports, tmp_path, monkeypatch):
    monkeypatch.setattr(docs, "_fetch", lambda url: b"%PDF-1.4 fake bytes")
    text = _install_fake_markitdown(monkeypatch, text="# Auto\n\nFrom the original.")
    ingest.ingest_reports(sample_reports, conn)
    docs_dir = str(tmp_path / "documents")
    paper = conn.execute(
        "SELECT * FROM corpus_item WHERE kind='paper' AND id="
        "(SELECT id FROM corpus_item WHERE kind='paper' ORDER BY id LIMIT 1)").fetchone()
    out = docs.auto_markdown(paper, docs_dir, conn)
    assert out == text
    # Cached on disk as article.auto.md and re-readable without re-converting.
    paper = conn.execute("SELECT * FROM corpus_item WHERE id=?", (paper["id"],)).fetchone()
    assert docs.read_auto_markdown(paper, docs_dir) == text
    assert docs.has_convertible_source(paper, docs_dir) is True


def test_auto_markdown_unavailable_returns_none(conn, sample_reports, tmp_path, monkeypatch):
    monkeypatch.setattr(docs, "_fetch", lambda url: b"FAKEDOC")
    # markitdown missing -> ImportError -> graceful None.
    monkeypatch.setitem(sys.modules, "markitdown", None)
    ingest.ingest_reports(sample_reports, conn)
    docs_dir = str(tmp_path / "documents")
    paper = conn.execute("SELECT * FROM corpus_item WHERE kind='paper' ORDER BY id LIMIT 1").fetchone()
    assert docs.auto_markdown(paper, docs_dir, conn) is None


def test_auto_markdown_no_source_document_returns_none(conn, sample_reports, tmp_path, monkeypatch):
    # A repo's stored doc is README.md, not a convertible source.* original.
    monkeypatch.setattr(docs, "_fetch", lambda url: b"FAKEDOC")
    _install_fake_markitdown(monkeypatch)
    ingest.ingest_reports(sample_reports, conn)
    docs_dir = str(tmp_path / "documents")
    repo = conn.execute("SELECT * FROM corpus_item WHERE kind='repo' LIMIT 1").fetchone()
    assert docs.auto_markdown(repo, docs_dir, conn) is None
    repo = conn.execute("SELECT * FROM corpus_item WHERE id=?", (repo["id"],)).fetchone()
    assert docs.has_convertible_source(repo, docs_dir) is False


# --------------------------------------------------------------------------
# feed ordering
# --------------------------------------------------------------------------
def test_feed_ordering(conn, sample_reports):
    ingest.ingest_reports(sample_reports, conn)
    rows = conn.execute(
        "SELECT title, signal FROM corpus_item ORDER BY signal DESC, id DESC").fetchall()
    signals = [r["signal"] for r in rows]
    assert signals == sorted(signals, reverse=True)


# --------------------------------------------------------------------------
# ai (fake opencode)
# --------------------------------------------------------------------------
def test_list_models_parsing():
    out = ai.list_models()
    provs = {g["provider"] for g in out["providers"]}
    assert "openai" in provs and "anthropic" in provs
    openai = next(g for g in out["providers"] if g["provider"] == "openai")
    assert any(m["id"] == "openai/gpt-fake-mini" for m in openai["models"])


def test_summarize_item():
    out = ai.summarize_item({"kind": "paper", "title": "T", "abstract": "A"}, "openai/gpt-fake")
    assert isinstance(out["summary"], list) and 1 <= len(out["summary"]) <= 4
    assert "mixture-of-experts" in out["terms"]


def test_explain_modes():
    e = ai.explain("context window", "explain", {"title": "T"}, "openai/gpt-fake")
    assert e["lead"] and e["body"] and e.get("analogy")
    s = ai.explain("context window", "summarize", {"title": "T"}, "openai/gpt-fake")
    assert "analogy" not in s


def test_suggest_links():
    others = [{"id": 3, "label": "Router"}, {"id": 7, "label": "Tokens"}]
    out = ai.suggest_links({"id": 1, "label": "MoE"}, others, "openai/gpt-fake")
    assert out == [3]


# --------------------------------------------------------------------------
# map
# --------------------------------------------------------------------------
def _save_entry(conn, term, span, item_id=None):
    cur = conn.execute(
        "INSERT INTO kb_entry (term, span_text, item_id, mode, model, lead, body, "
        "analogy, tag, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (term, span, item_id, "explain", "m", term + " lead", term + " body",
         None, "note", db.utcnow()))
    eid = cur.lastrowid
    conn.execute("INSERT INTO kb_message (kb_entry_id, role, content, created_at) "
                 "VALUES (?,?,?,?)", (eid, "assistant", term + " body", db.utcnow()))
    db.reindex_entry(conn, eid)
    map_store.ensure_concept_for_entry(conn, eid)
    conn.commit()
    return eid


def test_map_nodes_edges_position(conn):
    e1 = _save_entry(conn, "Router", "router")
    e2 = _save_entry(conn, "Experts", "experts")
    m = map_store.get_map(conn)
    assert len(m["nodes"]) == 2
    c1, c2 = m["nodes"][0]["id"], m["nodes"][1]["id"]
    eid = map_store.add_edge(conn, c1, c2, "manual")
    assert eid is not None
    # dedupe / reverse
    assert map_store.add_edge(conn, c2, c1, "manual") == eid
    map_store.set_position(conn, c1, 12.5, 80.0)
    node = next(n for n in map_store.get_map(conn)["nodes"] if n["id"] == c1)
    assert round(node["x"], 1) == 12.5 and round(node["y"], 1) == 80.0
    map_store.delete_edge(conn, eid)
    assert map_store.get_map(conn)["edges"] == []


def test_map_ai_links(conn):
    _save_entry(conn, "Router", "router")
    _save_entry(conn, "Experts", "experts")
    res = map_store.ai_links(conn, "openai/gpt-fake")
    assert res["added"] >= 1
    assert any(e["source"] == "ai" for e in map_store.get_map(conn)["edges"])


# --------------------------------------------------------------------------
# refresh (tracker stubbed)
# --------------------------------------------------------------------------
def test_run_refresh_state(tmp_path, monkeypatch, sample_reports):
    refresh.reset()
    db_path = str(tmp_path / "g.db")

    def fake_tracker(kind, days, reports_dir):
        # Pretend the pipeline wrote the sample sidecars into reports_dir.
        import shutil
        for name in os.listdir(sample_reports):
            shutil.copy(os.path.join(sample_reports, name), os.path.join(reports_dir, name))

    monkeypatch.setattr(refresh, "_run_tracker", fake_tracker)
    rdir = str(tmp_path / "out_reports")
    os.makedirs(rdir)

    def factory():
        c = db.connect(db_path)
        db.bootstrap(c)
        return c

    state = refresh.run_refresh("papers", 7, rdir, factory)
    assert state["status"] == "running"
    refresh.join(10)
    final = refresh.status()
    assert final["status"] == "done"
    assert final["counts"]["new"] >= 1


def test_run_refresh_ingests_despite_failing_tracker(tmp_path, monkeypatch, sample_reports):
    """A failing tracker must not stop the worker from ingesting the others.

    The repos tracker raises (GitHub rate-limit / no token in practice) while
    the papers tracker writes its sidecar. The worker must still ingest the
    papers, end status=done, and surface the repos error in the message.
    """
    refresh.reset()
    db_path = str(tmp_path / "g.db")

    def fake_tracker(kind, days, reports_dir):
        if kind == "repos":
            raise RuntimeError("GitHub rate limit exceeded")
        # papers: copy only the labpapers sidecar into the reports dir.
        import shutil
        for name in os.listdir(sample_reports):
            if name.startswith("labpapers_"):
                shutil.copy(os.path.join(sample_reports, name),
                            os.path.join(reports_dir, name))

    monkeypatch.setattr(refresh, "_run_tracker", fake_tracker)
    rdir = str(tmp_path / "out_reports")
    os.makedirs(rdir)

    def factory():
        c = db.connect(db_path)
        db.bootstrap(c)
        return c

    # kind="all" so both trackers run; repos fails, papers succeeds.
    refresh.run_refresh(None, 7, rdir, factory)
    refresh.join(10)
    final = refresh.status()

    assert final["status"] == "done"
    assert "repos failed" in final["message"]
    assert "GitHub rate limit" in final["message"]

    # The papers were actually ingested into corpus_item.
    c = db.connect(db_path)
    papers = c.execute("SELECT COUNT(*) c FROM corpus_item WHERE kind='paper'").fetchone()["c"]
    repos = c.execute("SELECT COUNT(*) c FROM corpus_item WHERE kind='repo'").fetchone()["c"]
    c.close()
    assert papers >= 1
    assert repos == 0


# --------------------------------------------------------------------------
# end-to-end HTTP through the server handler
# --------------------------------------------------------------------------
@pytest.fixture
def live_server(tmp_path, monkeypatch, sample_reports):
    monkeypatch.setattr(docs, "_fetch", lambda url: b"FAKEDOC")
    from university import server
    db_path = str(tmp_path / "g.db")
    docs_dir = str(tmp_path / "documents")
    ctx = server.AppContext(db_path, sample_reports, docs_dir, default_model="openai/gpt-fake")
    auth.add_user(ctx.conn, "maya", "pw123")
    ingest.ingest_reports(sample_reports, ctx.conn)
    httpd = server.make_server("127.0.0.1", 0, ctx)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    time.sleep(0.1)
    yield "http://127.0.0.1:{}".format(port)
    httpd.shutdown()
    httpd.server_close()


def _http(method, url, body=None, cookie=None):
    import urllib.request
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if cookie:
        req.add_header("Cookie", cookie)
    try:
        resp = urllib.request.urlopen(req)
        set_cookie = resp.headers.get("Set-Cookie")
        return resp.status, json.loads(resp.read().decode()), set_cookie
    except urllib.error.HTTPError as e:
        return e.code, None, None


def _http_raw(method, url, data=None, content_type=None, cookie=None):
    import urllib.request
    req = urllib.request.Request(url, data=data, method=method)
    if content_type:
        req.add_header("Content-Type", content_type)
    if cookie:
        req.add_header("Cookie", cookie)
    try:
        resp = urllib.request.urlopen(req)
        return resp.status, resp.read(), resp.headers.get("Content-Type")
    except urllib.error.HTTPError as e:
        return e.code, None, None


def test_markdown_attach_and_fetch(live_server):
    base = live_server
    # gated without a cookie
    status, _, _ = _http_raw("GET", base + "/api/item/1/markdown")
    assert status == 401
    status, _, _ = _http_raw("POST", base + "/api/item/1/markdown",
                             data=b"# x", content_type="text/markdown")
    assert status == 401

    status, _, setck = _http("POST", base + "/api/login",
                             {"username": "maya", "password": "pw123"})
    cookie = setck.split(";")[0]
    status, feed, _ = _http("GET", base + "/api/feed", cookie=cookie)
    item_id = feed["items"][0]["id"]
    item2 = feed["items"][1]["id"]

    # No markdown yet.
    status, item, _ = _http("GET", base + "/api/item/{}".format(item_id), cookie=cookie)
    assert status == 200 and item["has_markdown"] is False
    status, _, _ = _http_raw("GET", base + "/api/item/{}/markdown".format(item_id),
                             cookie=cookie)
    assert status == 404

    # Raw text/markdown upload.
    md = "# Heading\n\nHello **world**.".encode("utf-8")
    status, _, _ = _http_raw("POST", base + "/api/item/{}/markdown".format(item_id),
                             data=md, content_type="text/markdown", cookie=cookie)
    assert status == 200
    status, item, _ = _http("GET", base + "/api/item/{}".format(item_id), cookie=cookie)
    assert item["has_markdown"] is True
    status, body, ctype = _http_raw(
        "GET", base + "/api/item/{}/markdown".format(item_id), cookie=cookie)
    assert status == 200 and body.decode("utf-8") == "# Heading\n\nHello **world**."
    assert "text/markdown" in ctype

    # Minimal multipart/form-data upload on a second item.
    boundary = "----gymtestboundary"
    multipart = (
        "--{b}\r\n"
        'Content-Disposition: form-data; name="file"; filename="a.md"\r\n'
        "Content-Type: text/markdown\r\n\r\n"
        "## Multipart\r\n"
        "--{b}--\r\n"
    ).format(b=boundary).encode("utf-8")
    status, _, _ = _http_raw(
        "POST", base + "/api/item/{}/markdown".format(item2), data=multipart,
        content_type="multipart/form-data; boundary={}".format(boundary), cookie=cookie)
    assert status == 200
    status, body, _ = _http_raw(
        "GET", base + "/api/item/{}/markdown".format(item2), cookie=cookie)
    assert status == 200 and body.decode("utf-8") == "## Multipart"


def test_markdown_auto_then_user_override(live_server, monkeypatch):
    base = live_server
    _install_fake_markitdown(monkeypatch, text="# Auto\n\nFrom the original.")
    status, _, setck = _http("POST", base + "/api/login",
                             {"username": "maya", "password": "pw123"})
    cookie = setck.split(";")[0]
    status, feed, _ = _http("GET", base + "/api/feed", cookie=cookie)
    paper = next(i for i in feed["items"] if i["kind"] == "paper")
    repo = next(i for i in feed["items"] if i["kind"] == "repo")
    pid = paper["id"]

    # Item endpoint advertises a convertible source but has NOT converted yet.
    status, item, _ = _http("GET", base + "/api/item/{}".format(pid), cookie=cookie)
    assert status == 200
    assert item["has_markdown"] is False
    assert item["markdown_available"] is True
    assert item["markdown_source"] is None

    # First markdown GET triggers the lazy auto conversion and caches it.
    status, body, _ = _http_raw(
        "GET", base + "/api/item/{}/markdown".format(pid), cookie=cookie)
    assert status == 200 and body.decode("utf-8") == "# Auto\n\nFrom the original."
    status, item, _ = _http("GET", base + "/api/item/{}".format(pid), cookie=cookie)
    assert item["markdown_source"] == "auto"

    # A user upload overrides the auto version and is preferred thereafter.
    status, _, _ = _http_raw("POST", base + "/api/item/{}/markdown".format(pid),
                             data=b"# Mine\n\nUploaded.", content_type="text/markdown",
                             cookie=cookie)
    assert status == 200
    status, item, _ = _http("GET", base + "/api/item/{}".format(pid), cookie=cookie)
    assert item["has_markdown"] is True and item["markdown_source"] == "user"
    status, body, _ = _http_raw(
        "GET", base + "/api/item/{}/markdown".format(pid), cookie=cookie)
    assert body.decode("utf-8") == "# Mine\n\nUploaded."  # user wins over auto

    # An item with no convertible source falls back gracefully (404, no flag).
    status, item, _ = _http("GET", base + "/api/item/{}".format(repo["id"]), cookie=cookie)
    assert item["markdown_available"] is False
    status, _, _ = _http_raw(
        "GET", base + "/api/item/{}/markdown".format(repo["id"]), cookie=cookie)
    assert status == 404


def test_auth_gate_and_full_flow(live_server):
    base = live_server
    # gated without cookie
    status, _, _ = _http("GET", base + "/api/feed")
    assert status == 401
    # bad login
    status, _, _ = _http("POST", base + "/api/login", {"username": "maya", "password": "wrong"})
    assert status == 401
    # non-alphanumeric login rejected
    status, _, _ = _http("POST", base + "/api/login", {"username": "ma!ya", "password": "pw123"})
    assert status == 401
    # good login
    status, data, setck = _http("POST", base + "/api/login", {"username": "maya", "password": "pw123"})
    assert status == 200
    cookie = setck.split(";")[0]
    # feed works with cookie
    status, feed, _ = _http("GET", base + "/api/feed", cookie=cookie)
    assert status == 200 and len(feed["items"]) == 3
    item_id = feed["items"][0]["id"]
    # opening the item triggers ensure_document
    status, item, _ = _http("GET", base + "/api/item/{}".format(item_id), cookie=cookie)
    assert status == 200 and item["doc_path"]

    # ask -> save with full thread
    status, ask, _ = _http("POST", base + "/api/ask", {
        "span_text": "mixture-of-experts", "item_id": item_id, "mode": "explain",
        "model": "openai/gpt-fake"}, cookie=cookie)
    assert status == 200 and ask["answer"]["lead"]
    status, saved, _ = _http("POST", base + "/api/kb/save", {
        "span_text": "mixture-of-experts", "item_id": item_id, "mode": "explain",
        "model": "openai/gpt-fake", "answer": ask["answer"],
        "thread": [{"role": "user", "content": "what is the router"},
                   {"role": "assistant", "content": "the router picks experts"}]},
        cookie=cookie)
    assert status == 200
    entry_id = saved["entry"]["id"]
    assert saved["entry"]["source_doc_path"]
    assert saved["entry"]["source_url"]
    # whole thread persisted: 1 answer + 2 thread turns = 3 messages
    assert len(saved["entry"]["messages"]) == 3

    # follow-up after save appends server-side
    status, _, _ = _http("POST", base + "/api/ask", {
        "span_text": "mixture-of-experts", "item_id": item_id, "kb_entry_id": entry_id,
        "mode": "ask", "message": "and what about balancing", "model": "openai/gpt-fake"},
        cookie=cookie)
    assert status == 200
    status, full, _ = _http("GET", base + "/api/kb/{}".format(entry_id), cookie=cookie)
    assert len(full["messages"]) == 5  # 3 + (user + assistant)

    # search finds it by a word from a follow-up turn
    status, res, _ = _http("GET", base + "/api/kb/search?q=balancing", cookie=cookie)
    assert status == 200 and any(e["id"] == entry_id for e in res["entries"])
    # and a word from the original turn
    status, res, _ = _http("GET", base + "/api/kb/search?q=router", cookie=cookie)
    assert any(e["id"] == entry_id for e in res["entries"])

    # the saved term shows up as a map node
    status, mp, _ = _http("GET", base + "/api/map", cookie=cookie)
    assert len(mp["nodes"]) >= 1

    # models endpoint reflects fake opencode
    status, models, _ = _http("GET", base + "/api/models", cookie=cookie)
    assert any(g["provider"] == "openai" for g in models["providers"])

    # logout revokes
    status, _, _ = _http("POST", base + "/api/logout", {}, cookie=cookie)
    assert status == 200
    status, _, _ = _http("GET", base + "/api/feed", cookie=cookie)
    assert status == 401
