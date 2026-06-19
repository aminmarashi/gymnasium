from labpapers.cache import Cache
from labpapers.sources import anthropic_site as A
from labpapers.sources.anthropic_site import (
    AnthropicSiteSource,
    RESEARCH_URL,
    SITEMAP_URL,
)
from labpapers.sources.base import FetchContext

DETAIL_URL = "https://www.anthropic.com/research/in-window-paper"
STALE_URL = "https://www.anthropic.com/research/sitemap-only-stale"

SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset>
  <url><loc>https://www.anthropic.com/research/in-window-paper</loc>
       <lastmod>2026-06-18T10:00:00.000Z</lastmod></url>
  <url><loc>https://www.anthropic.com/research/sitemap-only-stale</loc>
       <lastmod>2026-06-17T10:00:00.000Z</lastmod></url>
  <url><loc>https://www.anthropic.com/research/team/interpretability</loc>
       <lastmod>2026-06-19T10:00:00.000Z</lastmod></url>
  <url><loc>https://www.anthropic.com/careers</loc>
       <lastmod>2026-06-19T10:00:00.000Z</lastmod></url>
</urlset>"""

# A sitemap-only candidate whose lastmod is recent but whose real publish date
# (read from the detail page) is months old -> must be excluded.
STALE_DETAIL = """<html><body><article>
<div class="PostDetail-module-scss-module__X__subjects"><span>Alignment</span></div>
<h1>A stale post</h1>
<div class="body-3 agate">Apr 2, 2026</div>
<div class="Body-module-scss-module__X__body"><p>This is older body content that is
plenty long enough to count as a summary paragraph for the parser.</p></div>
</article></body></html>"""

POLICY_DETAIL = """<html><body><article>
<div class="PostDetail-module-scss-module__X__subjects"><span>Policy</span></div>
<h1>A pure policy post</h1>
<div class="body-3 agate">Jun 17, 2026</div>
<div class="Body-module-scss-module__X__body"><p>A policy announcement with enough text
here to be treated as a summary paragraph by the detail parser logic.</p></div>
</article></body></html>"""


class FakeClient:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get_text(self, url, params=None):
        self.calls.append(url)
        return self.pages.get(url)


def _ctx(client, from_date="2026-06-12", to_date="2026-06-19"):
    return FetchContext(
        from_date=from_date, to_date=to_date, lab_keys=["anthropic"],
        client=client, cache=Cache(None, enabled=False),
    )


# --- pure parsers ---------------------------------------------------------
def test_parse_date():
    assert A._parse_date("Jun 8, 2026") == "2026-06-08"
    assert A._parse_date("June 8, 2026") == "2026-06-08"
    assert A._parse_date("Dec 18, 2025") == "2025-12-18"
    assert A._parse_date("not a date") is None
    assert A._parse_date(None) is None


def test_parse_listing(fixture):
    items = A.parse_listing(fixture("anthropic_listing.html"))
    assert len(items) == 2  # the /research/team/ link is excluded
    first = items[0]
    assert first["url"] == "https://www.anthropic.com/research/in-window-paper"
    assert A._parse_date(first["date"]) == "2026-06-18"
    assert first["categories"] == ["Interpretability"]


def test_parse_detail(fixture):
    d = A.parse_detail(fixture("anthropic_detail.html"))
    assert d["title"] == "Probing the internals of a language model"
    assert d["date"] == "2026-06-18"
    assert d["categories"] == ["Interpretability"]
    # footnote byline parsed; summary skips the byline paragraph
    assert d["authors"] == ["Jane Researcher", "John Scientist", "Mei Chen"]
    assert d["summary"].startswith("We study how a transformer")


def test_parse_detail_falls_back_to_meta_description():
    # No long prose paragraph in the body -> summary comes from meta description.
    html = ('<html><head>'
            '<meta name="description" content="A concise meta summary of the '
            'post that the parser should use when no long paragraph exists." />'
            '</head><body><article>'
            '<h1>A media-led post</h1>'
            '<div class="body-3 agate">Jun 18, 2026</div>'
            '<p>Short.</p>'
            '</article></body></html>')
    d = A.parse_detail(html)
    assert d["summary"].startswith("A concise meta summary")


def test_parse_detail_falls_back_to_og_description():
    html = ('<html><head>'
            '<meta property="og:description" content="An open-graph description '
            'used as the summary fallback when nothing else is available." />'
            '</head><body><article><h1>Title</h1></article></body></html>')
    d = A.parse_detail(html)
    assert d["summary"].startswith("An open-graph description")


def test_parse_detail_prefers_long_paragraph_over_meta(fixture):
    # When a real summary paragraph exists, the meta description is NOT used.
    d = A.parse_detail(fixture("anthropic_detail.html"))
    assert d["summary"].startswith("We study how a transformer")


def test_parse_sitemap_filters_research_only():
    entries = A.parse_sitemap(SITEMAP)
    urls = [u for u, _ in entries]
    assert "https://www.anthropic.com/research/in-window-paper" in urls
    assert "https://www.anthropic.com/research/sitemap-only-stale" in urls
    # /research/team/ index pages and non-research urls are excluded
    assert all("/research/team/" not in u for u in urls)
    assert all("/careers" not in u for u in urls)


def test_extract_authors_written_by_shape():
    from bs4 import BeautifulSoup
    html = ("<article><p>Written by Laura Luebbert. Based on research by "
            "Ferdous Nasri, Sarah Gurev, and Patrick Varilly.</p></article>")
    art = BeautifulSoup(html, "html.parser").find("article")
    assert A._extract_authors(art) == [
        "Laura Luebbert", "Ferdous Nasri", "Sarah Gurev", "Patrick Varilly"
    ]


def test_extract_authors_ignores_prose():
    from bs4 import BeautifulSoup
    html = "<article><p>Agentic coding has taken off across the industry.</p></article>"
    art = BeautifulSoup(html, "html.parser").find("article")
    assert A._extract_authors(art) == []


# --- the source end-to-end (offline) --------------------------------------
def test_fetch_keeps_in_window_excludes_old_and_stale(fixture):
    client = FakeClient({
        RESEARCH_URL: fixture("anthropic_listing.html"),
        SITEMAP_URL: SITEMAP,
        DETAIL_URL: fixture("anthropic_detail.html"),
        STALE_URL: STALE_DETAIL,
    })
    papers = AnthropicSiteSource().fetch(_ctx(client))
    assert len(papers) == 1
    p = papers[0]
    assert p.title == "Probing the internals of a language model"
    assert p.date == "2026-06-18"
    assert p.labs_matched == ["anthropic"]
    assert p.source_engines == ["anthropic-site"]
    assert p.primary_category == "Interpretability"
    assert [a.name for a in p.authors] == [
        "Jane Researcher", "John Scientist", "Mei Chen"
    ]
    assert p.source_url == DETAIL_URL
    # the out-of-window listing item is dropped without fetching its detail page
    assert "https://www.anthropic.com/research/old-paper" not in client.calls
    # the sitemap-only candidate WAS fetched (to verify its date) then dropped
    assert STALE_URL in client.calls


def test_fetch_excludes_pure_policy_post(fixture):
    sitemap = ("<urlset><url><loc>https://www.anthropic.com/research/policy-post"
               "</loc><lastmod>2026-06-17T10:00:00Z</lastmod></url></urlset>")
    client = FakeClient({
        RESEARCH_URL: "<html><body></body></html>",  # empty listing
        SITEMAP_URL: sitemap,
        "https://www.anthropic.com/research/policy-post": POLICY_DETAIL,
    })
    papers = AnthropicSiteSource().fetch(_ctx(client))
    assert papers == []  # in-window but pure Policy -> out of research scope


def test_fetch_degrades_when_all_fetches_fail():
    client = FakeClient({})  # every get_text returns None
    papers = AnthropicSiteSource().fetch(_ctx(client))
    assert papers == []


def test_fetch_noop_when_anthropic_not_selected(fixture):
    client = FakeClient({RESEARCH_URL: fixture("anthropic_listing.html")})
    ctx = FetchContext(
        from_date="2026-06-12", to_date="2026-06-19", lab_keys=["openai"],
        client=client, cache=Cache(None, enabled=False),
    )
    assert AnthropicSiteSource().fetch(ctx) == []
    assert client.calls == []  # nothing fetched when Anthropic isn't selected
