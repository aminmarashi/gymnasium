from labpapers import config
from labpapers.model import Paper, PaperAuthor
from labpapers.sources import affiliations

ARXIV_HTML = """
<!DOCTYPE html>
<html><head>
<meta name="citation_author_institution" content="Anthropic, San Francisco" />
</head>
<body>
<div class="ltx_authors">
  <span class="ltx_personname">Jane Doe</span>
  <span class="ltx_role_affiliation">Anthropic</span>
</div>
<p class="ltx_p">The rest of the paper mentions Google Scholar but that is body
text and must not be parsed for affiliations.</p>
</body></html>
"""


def test_parse_html_affiliations_extracts_frontmatter():
    chunks = affiliations.parse_html_affiliations(ARXIV_HTML)
    joined = " ".join(chunks)
    assert "Anthropic" in joined
    # the affiliation regex matches anthropic from the frontmatter
    matched = config.match_labs_by_affiliation(chunks)
    assert "anthropic" in matched
    # body-text "Google Scholar" must not leak into the affiliation chunks
    assert "Google Scholar" not in joined


def test_resolution_cache_roundtrip():
    res = affiliations.Resolution(
        labs=["deepseek"],
        evidence=["DeepSeek-AI"],
        resolved_via="openalex",
    )
    restored = affiliations.Resolution.from_cache(res.to_cache())
    assert restored.labs == ["deepseek"]
    assert restored.resolved_via == "openalex"
    assert restored.evidence == ["DeepSeek-AI"]


def _authorship(name, inst_ids, affils):
    return {
        "author": {"display_name": name, "id": "https://openalex.org/A" + name[:3]},
        "institutions": [{"id": "https://openalex.org/" + i} for i in inst_ids],
        "raw_affiliation_strings": affils,
    }


def test_labs_from_work_drops_persona_authors():
    # Persona "authors" even carry the real OpenAlex lab institution id, so they
    # must be skipped entirely; the only real author here is at a non-lab org.
    work = {"authorships": [
        _authorship("Ace (Claude Opus, Anthropic)",
                    ["I4210161460"], ["Anthropic AI"]),      # OpenAI inst id!
        _authorship("Kairo (DeepSeek)", [], ["DeepSeek"]),
        _authorship("Shalia Martin", ["I93085520"], ["Silicon Scaffolding"]),
    ]}
    labs, evidence, _ = affiliations._labs_from_work(work, only=None)
    assert labs == []
    assert evidence == []


def test_labs_from_work_keeps_real_author():
    work = {"authorships": [
        _authorship("Jane Researcher", [], ["DeepSeek-AI, Beijing"]),
    ]}
    labs, _, _ = affiliations._labs_from_work(work, only=None)
    assert labs == ["deepseek"]


def test_cache_key_is_scoped_by_lab_filter():
    # A narrow --labs run must not share a cache slot with the all-labs run.
    assert (affiliations._cache_key("2606.1", ["google"])
            != affiliations._cache_key("2606.1", None))
    # order-independent for the same set
    assert (affiliations._cache_key("2606.1", ["google", "anthropic"])
            == affiliations._cache_key("2606.1", ["anthropic", "google"]))


def test_cache_key_is_versioned():
    # The resolver-version prefix invalidates resolutions written by older
    # semantics (stale "unresolved" false-negatives) on existing caches.
    key = affiliations._cache_key("2606.1", None)
    assert key.startswith(affiliations._RESOLVER_CACHE_VERSION + "|")
    # an unversioned key (the pre-fix shape) must NOT collide with the new key.
    assert key != "2606.1|*"


def test_has_usable_affiliation_strings_ignores_bare_institution_ids():
    # institution ids without raw affiliation text are NOT enough to settle a
    # paper -> the HTML fallback should still get a chance.
    only_inst = [PaperAuthor(name="A", institution_ids=["I93085520"],
                             raw_affiliation_strings=[])]
    assert not affiliations._has_usable_affiliation_strings(only_inst)
    # empty / whitespace / junk strings are unusable too
    junky = [PaperAuthor(name="B", raw_affiliation_strings=["  ", ""]),
             PaperAuthor(name="C",
                         raw_affiliation_strings=["Anthropic, OpenAI, DeepSeek"])]
    assert not affiliations._has_usable_affiliation_strings(junky)
    # a clean, non-junk string IS usable -> the paper is settled by OpenAlex
    usable = [PaperAuthor(name="D", raw_affiliation_strings=["MIT, Cambridge"])]
    assert affiliations._has_usable_affiliation_strings(usable)


class _FakeResolveClient:
    """Minimal client: OpenAlex DOI lookup via get_json, arXiv HTML via get_text."""

    def __init__(self, works, html):
        self._works = works
        self._html = html
        self.text_calls = []

    def get_json(self, url, params=None):
        return {"results": self._works, "meta": {}}

    def get_text(self, url, params=None):
        self.text_calls.append(url)
        return self._html


def test_resolve_falls_back_to_html_when_openalex_affiliations_empty():
    # OpenAlex HAS the work and a (non-lab) institution id, but the raw
    # affiliation strings are empty -> no lab matches and the paper must fall
    # back to the arXiv HTML author block, where "Anthropic" is revealed.
    work = {
        "doi": "https://doi.org/10.48550/arXiv.2606.99",
        "authorships": [{
            "author": {"display_name": "Jane Doe",
                       "id": "https://openalex.org/A123"},
            "institutions": [{"id": "https://openalex.org/I93085520"}],  # non-lab
            "raw_affiliation_strings": [],  # OpenAlex-present-but-empty
        }],
    }
    html = ('<html><body><div class="ltx_authors">'
            '<span class="ltx_role_affiliation">Anthropic</span>'
            '</div></body></html>')
    client = _FakeResolveClient([work], html)
    paper = Paper(title="t", arxiv_id="2606.99")

    res = affiliations.resolve(client, [paper], fetch_html=True)

    assert "https://arxiv.org/html/2606.99" in client.text_calls
    assert res["2606.99"].labs == ["anthropic"]
    assert res["2606.99"].resolved_via == "html"


def test_html_fallback_retains_openalex_author_ids():
    # OpenAlex has the work (with author ids) but empty affiliation strings, so
    # the paper falls back to HTML. The HTML-derived Resolution must still carry
    # the OpenAlex author ids, or the paper silently loses prominence / Key
    # People signal.
    work = {
        "doi": "https://doi.org/10.48550/arXiv.2606.99",
        "authorships": [{
            "author": {"display_name": "Jane Doe",
                       "id": "https://openalex.org/A123"},
            "institutions": [{"id": "https://openalex.org/I93085520"}],  # non-lab
            "raw_affiliation_strings": [],  # OpenAlex-present-but-empty
        }],
    }
    html = ('<html><body><div class="ltx_authors">'
            '<span class="ltx_role_affiliation">Anthropic</span>'
            '</div></body></html>')
    client = _FakeResolveClient([work], html)
    paper = Paper(title="t", arxiv_id="2606.99")

    res = affiliations.resolve(client, [paper], fetch_html=True)

    r = res["2606.99"]
    assert r.resolved_via == "html"
    assert r.labs == ["anthropic"]
    # the OpenAlex author id survives the HTML fallback
    assert [a.openalex_id for a in r.authors] == ["A123"]
