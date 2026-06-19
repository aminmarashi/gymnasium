"""Anthropic publications source: parse anthropic.com/research directly.

OpenAlex reports zero works for Anthropic and the arXiv path only catches the
fraction of Anthropic work that lands on arXiv, so this source reads Anthropic's
own research listing. It is grounded against the live site:

  - https://www.anthropic.com/research -- a listing of recent publications, each
    item carrying a publish date ("Jun 18, 2026"), a subject/category, a title,
    and a /research/<slug> detail link.
  - https://www.anthropic.com/sitemap.xml -- 100+ /research/<slug> urls with a
    <lastmod>. The listing paginates older items away, so the sitemap is used to
    discover extra candidates. <lastmod> is a MODIFIED date, not a publish date
    (a Sep-2025 post can carry a Jun-2026 lastmod), so it is only a coarse
    pre-filter; the authoritative in-window decision uses the publish date read
    from the candidate's own detail page.
  - the detail page -- carries the canonical title, publish date, subject(s),
    a best-effort author byline, and a summary paragraph.

Every fetch is wrapped so a listing/sitemap/detail failure degrades the run
(fewer Anthropic papers) rather than killing it, and every fetched document is
cached via the shared cache for politeness.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from .. import config
from ..model import Paper, PaperAuthor
from .base import FetchContext

BASE_URL = "https://www.anthropic.com"
RESEARCH_URL = BASE_URL + "/research"
SITEMAP_URL = BASE_URL + "/sitemap.xml"

# Safety backstop on how many sitemap-discovered candidates we will fetch a
# detail page for in one run. Comfortably above a normal window's count.
MAX_SITEMAP_DETAIL_FETCHES = 80

# Longest summary paragraph we keep from a detail page.
MAX_SUMMARY_LEN = 600

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_DATE_RE = re.compile(r"([A-Za-z]{3,9})\s+(\d{1,2}),\s*(\d{4})")
_WRITTEN_BY_RE = re.compile(r"^\s*written by\s+", re.I)
_RESEARCH_BY_RE = re.compile(r"\bbased on research by\b", re.I)
# A plausible person name: 1-5 capitalized tokens (allowing initials, apostrophes,
# hyphens). Deliberately strict so prose is not mistaken for an author list.
_NAME_RE = re.compile(r"^[A-Z][A-Za-z.'’\-]*(?:\s+[A-Z][A-Za-z.'’\-]*){0,4}$")

# Sitemap parsing (namespace-agnostic, tolerant of a missing <lastmod>).
_URL_BLOCK_RE = re.compile(r"<url>(.*?)</url>", re.I | re.S)
_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
_LASTMOD_RE = re.compile(r"<lastmod>\s*([^<\s]*)\s*</lastmod>", re.I)


def _class_contains(substr: str):
    def predicate(value):
        if not value:
            return False
        joined = " ".join(value if isinstance(value, list) else [value])
        return substr in joined
    return predicate


def _parse_date(text: Optional[str]) -> Optional[str]:
    """'Jun 8, 2026' -> '2026-06-08' (and 'June 8, 2026'). None if unparseable."""

    if not text:
        return None
    m = _DATE_RE.search(text)
    if not m:
        return None
    mon = _MONTHS.get(m.group(1)[:3].lower())
    if not mon:
        return None
    return "%04d-%02d-%02d" % (int(m.group(3)), mon, int(m.group(2)))


def _canon_url(href: str) -> str:
    """Absolute, canonical (no query/fragment/trailing slash) anthropic url."""

    href = (href or "").strip()
    if href.startswith("//"):
        href = "https:" + href
    elif href.startswith("/"):
        href = BASE_URL + href
    href = href.split("#", 1)[0].split("?", 1)[0]
    if href.endswith("/"):
        href = href[:-1]
    return href


def _slug_title(url: str) -> str:
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    return slug.replace("-", " ").replace("_", " ").strip().title()


def _split_names(text: str) -> List[str]:
    """Split 'A, B, and C' / 'A and B' / 'A, B, C' into name parts."""

    text = re.sub(r",?\s+and\s+", ", ", text)
    return [p.strip(" .;’'") for p in text.split(",") if p.strip(" .;’'")]


def _looks_like_name_list(parts: List[str]) -> bool:
    return bool(parts) and len(parts) <= 25 and all(_NAME_RE.match(p) for p in parts)


def _extract_authors(article) -> List[str]:
    """Best-effort author byline extraction from a detail page's article body.

    Handles the two byline shapes Anthropic uses: a dedicated footnote-styled
    paragraph that is purely a name list, and a leading "Written by X. Based on
    research by Y, Z" paragraph. Returns [] when no confident byline is found
    (most posts) -- the paper is still kept, just without authors.
    """

    if article is None:
        return []
    # Shape 1: the first footnote-class paragraph is often a pure author list.
    for p in article.find_all("p", class_=_class_contains("footnote")):
        text = p.get_text(" ", strip=True)
        if not text:
            continue
        parts = _split_names(text)
        if _looks_like_name_list(parts):
            return parts
        break  # only the first footnote paragraph is a candidate byline
    # Shape 2: a leading "Written by ... [Based on research by ...]" paragraph.
    for p in article.find_all("p"):
        text = p.get_text(" ", strip=True)
        if not text:
            continue
        if _WRITTEN_BY_RE.match(text):
            m = _RESEARCH_BY_RE.search(text)
            head = text[: m.start()] if m else text
            tail = text[m.end():] if m else ""
            head = _WRITTEN_BY_RE.sub("", head)
            names = _split_names(head) + (_split_names(tail) if tail else [])
            names = [n for n in names if _NAME_RE.match(n)]
            if names:
                return names
        break  # only the first body paragraph can be the byline
    return []


def parse_listing(html: str) -> List[Dict]:
    """Parse the /research listing into {title, date, categories, url} items."""

    soup = BeautifulSoup(html or "", "html.parser")
    items: List[Dict] = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href.startswith("/research/") or href.startswith("/research/team/"):
            continue
        if not _class_contains("listItem")(a.get("class")):
            continue
        url = _canon_url(href)
        if url in seen:
            continue
        seen.add(url)
        time_el = a.find("time")
        subj = a.find("span", class_=_class_contains("subject"))
        title = a.find("span", class_=_class_contains("title"))
        cats = [subj.get_text(" ", strip=True)] if subj and subj.get_text(strip=True) else []
        items.append({
            "title": title.get_text(" ", strip=True) if title else None,
            "date": time_el.get_text(strip=True) if time_el else None,
            "categories": cats,
            "url": url,
        })
    return items


def parse_detail(html: str) -> Dict:
    """Parse a /research/<slug> detail page into title/date/categories/authors/summary."""

    soup = BeautifulSoup(html or "", "html.parser")

    title = None
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        title = h1.get_text(" ", strip=True)
    if not title:
        og = soup.find("meta", attrs={"property": "og:title"})
        if og and og.get("content"):
            title = og["content"].strip()

    date = None
    for div in soup.find_all("div", class_=_class_contains("agate")):
        date = _parse_date(div.get_text(" ", strip=True))
        if date:
            break

    categories: List[str] = []
    subjects = soup.find(class_=_class_contains("subjects"))
    if subjects:
        for span in subjects.find_all("span"):
            t = span.get_text(" ", strip=True)
            if t:
                categories.append(t)
        if not categories:
            t = subjects.get_text(" ", strip=True)
            if t:
                categories.append(t)

    article = soup.find("article")
    authors = _extract_authors(article)

    summary = ""
    scope = article or soup
    for p in scope.find_all("p"):
        text = p.get_text(" ", strip=True)
        if not text or len(text) < 80:
            continue
        # Skip the byline ("Written by ...") and any pure author-list paragraph.
        if _WRITTEN_BY_RE.match(text) or _looks_like_name_list(_split_names(text)):
            continue
        summary = text[:MAX_SUMMARY_LEN].rstrip()
        break

    # Fall back to the page's meta description when no long paragraph was found
    # (some posts lead with media/components rather than a prose paragraph).
    if not summary:
        for attrs in ({"name": "description"}, {"property": "og:description"}):
            meta = soup.find("meta", attrs=attrs)
            content = meta.get("content").strip() if meta and meta.get("content") else ""
            if content:
                summary = content[:MAX_SUMMARY_LEN].rstrip()
                break

    return {
        "title": title,
        "date": date,
        "categories": categories,
        "authors": authors,
        "summary": summary,
    }


def parse_sitemap(xml: str) -> List["tuple"]:
    """Return [(canonical_url, lastmod)] for /research/<slug> sitemap entries.

    Excludes /research/team/<...> index pages and any multi-segment paths.
    """

    out: List[tuple] = []
    seen = set()
    for block in _URL_BLOCK_RE.findall(xml or ""):
        loc_m = _LOC_RE.search(block)
        if not loc_m:
            continue
        loc = loc_m.group(1).strip()
        if "/research/" not in loc:
            continue
        path = loc.split("/research/", 1)[1].rstrip("/")
        if not path or path.startswith("team/") or "/" in path:
            continue
        url = _canon_url(loc)
        if url in seen:
            continue
        seen.add(url)
        lm = _LASTMOD_RE.search(block)
        out.append((url, (lm.group(1).strip() if lm else "")))
    return out


class AnthropicSiteSource:
    name = "anthropic-site"

    def _get(self, ctx: FetchContext, url: str) -> Optional[str]:
        cached = ctx.cache.get("anthropic", url)
        if cached:
            return cached
        try:
            text = ctx.client.get_text(url)
        except Exception:
            return None
        if text:
            ctx.cache.set("anthropic", url, text)
        return text

    def fetch(self, ctx: FetchContext) -> List[Paper]:
        if "anthropic" not in ctx.lab_keys:
            return []

        # url -> {date, categories, title, from_listing}
        candidates: "Dict[str, Dict]" = {}

        # 1) listing: authoritative publish dates for recent items.
        listing_html = self._get(ctx, RESEARCH_URL)
        if listing_html:
            try:
                items = parse_listing(listing_html)
            except Exception:
                items = []
            for it in items:
                candidates[it["url"]] = {
                    "date": _parse_date(it.get("date")),
                    "categories": it.get("categories") or [],
                    "title": it.get("title"),
                    "from_listing": True,
                }

        # 2) sitemap: discover candidates the listing paginated away. lastmod is
        # only a coarse pre-filter (publish <= lastmod), verified per detail page.
        sitemap_xml = self._get(ctx, SITEMAP_URL)
        if sitemap_xml:
            try:
                entries = parse_sitemap(sitemap_xml)
            except Exception:
                entries = []
            added = 0
            for url, lastmod in entries:
                if url in candidates:
                    continue
                if not lastmod or lastmod[:10] < ctx.from_date:
                    continue
                if added >= MAX_SITEMAP_DETAIL_FETCHES:
                    break
                candidates[url] = {
                    "date": None, "categories": [], "title": None,
                    "from_listing": False,
                }
                added += 1

        # 3) resolve each candidate to an in-window Anthropic Paper.
        papers: List[Paper] = []
        for url, meta in candidates.items():
            date = meta["date"]
            # A listing item already out of window needs no detail fetch.
            if meta["from_listing"] and date is not None and not (
                ctx.from_date <= date <= ctx.to_date
            ):
                continue

            detail: Optional[Dict] = None
            if date is None or meta["from_listing"]:
                detail_html = self._get(ctx, url)
                if detail_html:
                    try:
                        detail = parse_detail(detail_html)
                    except Exception:
                        detail = None
            if detail and detail.get("date"):
                date = detail["date"]
            if not date or not (ctx.from_date <= date <= ctx.to_date):
                continue

            cats = (detail.get("categories") if detail else None) or meta["categories"]
            if not config.anthropic_category_in_scope(cats):
                continue

            title = (detail.get("title") if detail else None) or meta["title"] \
                or _slug_title(url)
            author_names = (detail.get("authors") if detail else None) or []
            summary = (detail.get("summary") if detail else None) or ""
            cat_display = ", ".join(cats) if cats else None

            papers.append(Paper(
                title=title,
                date=date,
                abstract=summary,
                source_url=url,
                abs_url=url,
                primary_category=cat_display,
                categories=list(cats),
                labs_matched=["anthropic"],
                source_engines=["anthropic-site"],
                affiliation_evidence=[url],
                authors=[PaperAuthor(name=n) for n in author_names],
                resolved_via="anthropic-site",
            ))
        return papers
