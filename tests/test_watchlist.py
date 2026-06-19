from labpapers import config, pipeline, report, watchlist as wl_config
from labpapers.model import Paper, PaperAuthor
from labpapers.pipeline import Watchlist
from labpapers.sources import openalex, watchlist_institutions, watchlist_people
from labpapers.sources.watchlist_institutions import ResolvedInstitution
from labpapers.sources.watchlist_people import (
    ResolvedPerson,
    _best_person_candidate,
    recent_works,
    resolve_people,
)


def _author_rec(aid, name, cited, works=50, cs=True):
    topics = [{"field": {"display_name": "Computer Science"}}] if cs else \
        [{"field": {"display_name": "Medicine"}}]
    return {
        "id": "https://openalex.org/" + aid,
        "display_name": name,
        "cited_by_count": cited,
        "works_count": works,
        "summary_stats": {"h_index": 30},
        "topics": topics,
        "last_known_institutions": [{"display_name": "University of Amsterdam"}],
    }


class _FakeClient:
    """Minimal client whose get_json returns a canned author-search payload."""

    def __init__(self, results):
        self._results = results

    def get_json(self, url, params=None):
        return {"results": self._results, "meta": {"next_cursor": None}}


# --- People resolution -----------------------------------------------------
def test_best_person_candidate_picks_cs_skips_non_cs_namesake():
    # A higher-cited non-CS namesake is first, but the AI/CS profile wins.
    records = [
        _author_rec("A2", "Jane Doe", 90000, cs=False),  # non-CS, more cites
        _author_rec("A1", "Jane Doe", 5000, cs=True),     # the CS researcher
    ]
    match = _best_person_candidate(records)
    assert match and match["id"].endswith("A1")


def test_best_person_candidate_none_when_no_cs():
    records = [_author_rec("A2", "Med Person", 90000, cs=False)]
    assert _best_person_candidate(records) is None


def test_best_person_candidate_works_threshold_prefers_plausible():
    thin = _author_rec("A1", "Thin Stub", 100, works=1, cs=True)
    solid = _author_rec("A2", "Solid", 50, works=80, cs=True)
    # both AI/CS; the one clearing the works bar is preferred even with fewer cites
    assert _best_person_candidate([thin, solid])["id"].endswith("A2")


def _author_rec_inst(aid, name, cited, works, country, inst_name="Some Inst", cs=True):
    rec = _author_rec(aid, name, cited, works=works, cs=cs)
    rec["last_known_institutions"] = [
        {"display_name": inst_name, "country_code": country}
    ]
    return rec


def test_best_person_candidate_unresolved_when_only_below_threshold():
    # The ONLY AI/CS match is a thin 2-work stub (the live "Jelle Zuidema" case):
    # it is below the plausibility bar, so resolution returns None (unresolved)
    # rather than picking it.
    thin = _author_rec("A1", "Jelle Zuidema", 0, works=2, cs=True)
    assert _best_person_candidate([thin]) is None


def test_best_person_candidate_prefers_nl_over_higher_cited_foreign():
    # The "Raquel Fernandez" case: a higher-cited foreign AI/CS namesake vs. the
    # NL-based UvA researcher. Both clear the bar; the NL affiliation wins so the
    # medical/foreign namesake is not picked.
    foreign = _author_rec_inst("A1", "Raquel Fernandez", 2721, 222, "DE",
                               inst_name="LMU Klinikum", cs=True)
    nl = _author_rec_inst("A2", "Raquel Fernandez", 461, 63, "NL",
                          inst_name="University of Amsterdam", cs=True)
    assert _best_person_candidate([foreign, nl])["id"].endswith("A2")


def test_best_person_candidate_keeps_dominant_profile_over_thin_nl_stub():
    # The "Max Welling" case: the real, far-more-cited profile carries NO NL tag,
    # while a thin local namesake stub IS at a NL institution. The NL preference
    # must NOT displace the overwhelmingly more prominent real profile.
    real = _author_rec_inst("A1", "Max Welling", 64447, 528, None,
                            inst_name="", cs=True)
    real["last_known_institutions"] = []  # OpenAlex lists no institution
    stub = _author_rec_inst("A2", "Max Welling", 2, 20, "NL",
                            inst_name="University of Amsterdam", cs=True)
    assert _best_person_candidate([real, stub])["id"].endswith("A1")


def test_resolve_people_records_profile_and_caches():
    client = _FakeClient([_author_rec("A1", "Max Welling", 120000, works=300)])
    people = [{"name": "Max Welling", "note": "n", "verify": False}]
    out = resolve_people(client, people)
    assert len(out) == 1
    rp = out[0]
    assert rp.status == "resolved"
    assert rp.openalex_id == "A1"
    assert rp.display_name == "Max Welling"
    assert rp.last_institution_name == "University of Amsterdam"
    assert rp.is_giant is True  # >= giant cited-by threshold


def test_resolve_people_unresolved_when_no_cs_match():
    client = _FakeClient([_author_rec("A9", "Some Name", 1000, cs=False)])
    out = resolve_people(client, [{"name": "Some Name"}])
    assert out[0].status == "unresolved"
    assert out[0].openalex_id is None


# --- institution resolution (NL-only) --------------------------------------
def _inst_rec(iid, name, works, country):
    return {
        "id": "https://openalex.org/" + iid,
        "display_name": name,
        "works_count": works,
        "country_code": country,
    }


def test_resolve_institutions_people_tracked_skips_search():
    # A people_tracked node never resolves to an OpenAlex id and is never pulled.
    insts = [{"label": "Qualcomm AI Research / QUVA", "search_term": "Qualcomm",
              "people_tracked": True, "note": "covered via people"}]
    out = watchlist_institutions.resolve_institutions(_FakeClient([]), insts)
    assert out[0].status == "people-tracked"
    assert out[0].openalex_id is None
    assert out[0].note


def test_resolve_institutions_resolves_nl_specific():
    # A real NL institution resolves to the top NL-constrained candidate.
    client = _FakeClient([_inst_rec("I1", "University of Amsterdam", 234282, "NL")])
    insts = [{"label": "University of Amsterdam",
              "search_term": "University of Amsterdam"}]
    out = watchlist_institutions.resolve_institutions(client, insts)
    assert out[0].status == "resolved"
    assert out[0].openalex_id == "I1"
    assert out[0].display_name == "University of Amsterdam"


class _RecordingCache:
    """In-memory cache that records every set() so tests can assert non-caching."""

    def __init__(self):
        self.store = {}
        self.sets = []

    def get(self, namespace, key):
        return self.store.get((namespace, key))

    def set(self, namespace, key, value):
        self.sets.append((namespace, key, value))
        self.store[(namespace, key)] = value


def test_resolve_institutions_no_nl_match_marks_unresolved():
    # An UNFLAGGED node whose NL search returns no match degrades to 'unresolved'
    # (non-fatal), NOT people-tracked, and NEVER falls back to a global org.
    cache = _RecordingCache()
    out = watchlist_institutions.resolve_institutions(
        _FakeClient([]), [{"label": "X", "search_term": "Qualcomm"}], cache=cache
    )
    assert out[0].status == "unresolved"
    assert out[0].openalex_id is None
    # The transient/empty failure must NOT be cached, so a later run can resolve.
    assert cache.sets == []


def test_resolve_institutions_search_error_marks_unresolved_uncached():
    # A search that raises is transient: unresolved, and not cached.
    class _BoomClient:
        def get_json(self, url, params=None):
            raise RuntimeError("network down")

    cache = _RecordingCache()
    out = watchlist_institutions.resolve_institutions(
        _BoomClient(), [{"label": "X", "search_term": "Qualcomm"}], cache=cache
    )
    assert out[0].status == "unresolved"
    assert cache.sets == []


def test_resolve_institutions_caches_only_successful_resolution():
    # A genuine NL resolution IS cached so later runs are cheap.
    cache = _RecordingCache()
    client = _FakeClient([_inst_rec("I1", "University of Amsterdam", 234282, "NL")])
    out = watchlist_institutions.resolve_institutions(
        client, [{"label": "University of Amsterdam",
                  "search_term": "University of Amsterdam"}], cache=cache
    )
    assert out[0].status == "resolved"
    assert len(cache.sets) == 1
    assert cache.sets[0][2]["openalex_id"] == "I1"


def test_resolve_institutions_stale_empty_cache_is_remiss_then_reresolved():
    # A stale empty/{} cache entry (written by an older resolver under the same
    # key) must be treated as a MISS: the resolver ignores it, performs a fresh
    # resolution, and caches ONLY the genuine successful result.
    cache = _RecordingCache()
    term = "University of Amsterdam"
    stale_key = (
        watchlist_institutions._INSTITUTION_CACHE_VERSION + "|" + term.lower()
    )
    cache.store[("watchlist_institution", stale_key)] = {}  # stale empty entry
    client = _FakeClient([_inst_rec("I1", "University of Amsterdam", 234282, "NL")])
    out = watchlist_institutions.resolve_institutions(
        client, [{"label": term, "search_term": term}], cache=cache
    )
    assert out[0].status == "resolved"
    assert out[0].openalex_id == "I1"
    # Only the genuine resolution is written; the stale empty is overwritten by it.
    assert len(cache.sets) == 1
    assert cache.sets[0][2]["openalex_id"] == "I1"


def test_people_tracked_institution_not_paper_pulled():
    # The pipeline only pulls papers for resolved institutions.
    pt = ResolvedInstitution(label="Qualcomm AI Research / QUVA",
                             search_term="Qualcomm", status="people-tracked")
    assert pt.status != "resolved"
    md = report.render_markdown(_result_with_watchlist_status(pt))
    assert "tracked via people" in md


def _result_with_watchlist_status(inst):
    res = _result_with_watchlist()
    res.watchlist.institutions = [inst]
    return res


# --- recent_works topic filtering ------------------------------------------
def _work(wid, title, field):
    return {
        "id": "https://openalex.org/" + wid,
        "title": title,
        "display_name": title,
        "publication_date": "2026-06-10",
        "primary_topic": {
            "display_name": title,
            "field": {"display_name": field},
            "subfield": {"display_name": "Artificial Intelligence"},
        },
        "authorships": [{
            "author": {"id": "https://openalex.org/A1",
                       "display_name": "Max Welling"},
        }],
    }


def test_recent_works_keeps_genai_drops_non_genai(monkeypatch):
    genai = _work("W1", "LLM agents for tool use", "Computer Science")
    nongenai = _work("W2", "Protein folding study", "Medicine")
    monkeypatch.setattr(
        openalex, "works_by_author", lambda *a, **k: [genai, nongenai]
    )
    papers = recent_works(
        _FakeClient([]), "A1", "Max Welling", "2026-06-01", "2026-06-19"
    )
    titles = [p.title for p in papers]
    assert "LLM agents for tool use" in titles
    assert "Protein folding study" not in titles  # excluded by structured filter
    assert papers[0].watchlist_people == ["Max Welling"]


# --- institution-wide CS-field gate ----------------------------------------
def _inst_work(wid, title, field, subfield="General"):
    return {
        "id": "https://openalex.org/" + wid,
        "title": title,
        "display_name": title,
        "publication_date": "2026-06-10",
        "primary_topic": {
            "display_name": title,
            "field": {"display_name": field},
            "subfield": {"display_name": subfield},
        },
        "authorships": [{
            "author": {"id": "https://openalex.org/A1", "display_name": "X"},
        }],
    }


def test_institution_works_drops_non_cs_softscience(monkeypatch):
    # A whole university emits soft-science papers that mention GenAI; only the
    # CS-primary-field ones survive the institution gate.
    cs = _inst_work("W1", "Multimodal vision-language retrieval",
                    "Computer Science", "Artificial Intelligence")
    soft = _inst_work("W2", "A reporting checklist for large language models",
                      "Social Sciences", "General Social Sciences")
    psych = _inst_work("W3", "Generative AI and clinical response shift",
                       "Psychology", "Clinical Psychology")
    monkeypatch.setattr(
        openalex, "works_by_institutions", lambda *a, **k: [cs, soft, psych]
    )
    papers = watchlist_institutions.institution_works(
        _FakeClient([]), "University of Amsterdam", "I1",
        "2026-06-01", "2026-06-19",
    )
    titles = [p.title for p in papers]
    assert "Multimodal vision-language retrieval" in titles
    assert "A reporting checklist for large language models" not in titles
    assert "Generative AI and clinical response shift" not in titles
    assert papers[0].watchlist_institution == ["University of Amsterdam"]


# --- union/dedup with lab papers -------------------------------------------
def test_watchlist_institution_paper_dedups_with_lab_paper():
    lab = Paper(title="Shared Paper", arxiv_id="2606.1", labs_matched=["google"],
                source_engines=["openalex-institutions"])
    inst = Paper(title="shared   paper", arxiv_id="2606.1",
                 watchlist_institution=["University of Amsterdam"],
                 source_engines=["watchlist-institutions"])
    merged = pipeline.dedup_papers([lab, inst])
    assert len(merged) == 1
    assert merged[0].labs_matched == ["google"]
    assert merged[0].watchlist_institution == ["University of Amsterdam"]


def test_watchlist_people_tag_merges_on_dedup():
    a = Paper(title="P", arxiv_id="2606.2", watchlist_people=["Max Welling"])
    b = Paper(title="P", arxiv_id="2606.2", watchlist_people=["Emiel Hoogeboom"])
    merged = pipeline.dedup_papers([a, b])
    assert len(merged) == 1
    assert set(merged[0].watchlist_people) == {"Max Welling", "Emiel Hoogeboom"}


# --- report rendering ------------------------------------------------------
def _result_with_watchlist():
    paper = Paper(
        title="Equivariant Diffusion", date="2026-06-10",
        abs_url="https://arxiv.org/abs/2606.9",
        watchlist_people=["Max Welling"],
        watchlist_institution=["University of Amsterdam"],
        prominence_available=True,
    )
    welling = ResolvedPerson(
        name="Max Welling", note="AMLab", verify=False, status="resolved",
        openalex_id="A1", display_name="Max Welling",
        last_institution_name="University of Amsterdam",
        cited_by_count=120000, h_index=120, works_count=300, is_giant=True,
        papers=[paper],
    )
    salimans = ResolvedPerson(
        name="Tim Salimans", verify=True, status="resolved", openalex_id="A2",
        display_name="Tim Salimans", last_institution_name="Google DeepMind",
        cited_by_count=40000, h_index=60, is_giant=True, papers=[],
    )
    kingma = ResolvedPerson(
        name="Diederik P. Kingma", verify=False, abroad=True, status="resolved",
        openalex_id="A3", display_name="Durk Kingma",
        last_institution_name="Anthropic", cited_by_count=200000, h_index=90,
        is_giant=True, papers=[],
    )
    uva = ResolvedInstitution(
        label="University of Amsterdam", search_term="University of Amsterdam",
        status="resolved", openalex_id="I1", display_name="University of Amsterdam",
        papers=[paper],
    )
    msr = ResolvedInstitution(
        label="Microsoft Research AI4Science Amsterdam",
        search_term="Microsoft Research", status="resolved", openalex_id="I2",
        display_name="Microsoft Research", papers=[],
    )
    watch = Watchlist(
        people=[welling, salimans],
        people_abroad=[kingma],
        institutions=[uva, msr],
        companies=wl_config.REFERENCE_COMPANIES,
        exclusions_note=wl_config.EXCLUSIONS_NOTE,
    )
    return pipeline.Result(
        papers=[paper], people_overall=[], people_by_lab={},
        from_date="2026-06-12", to_date="2026-06-19",
        labs=["google"], per_lab_counts={"google": 0}, watchlist=watch,
    )


def test_markdown_renders_watchlist_section():
    md = report.render_markdown(_result_with_watchlist())
    wl_idx = md.index("## Netherlands GenAI map (watchlist)")
    papers_idx = md.index("## Papers by lab")
    assert wl_idx < papers_idx  # watchlist sits ABOVE Papers by lab
    assert "### People" in md
    assert "Max Welling" in md
    # verify-affiliation marker present for Salimans
    assert "**verify affiliation**" in md
    # abroad sub-bucket holds Kingma, distinct from NL people
    abroad_idx = md.index("#### Dutch-origin, abroad")
    assert "Diederik P. Kingma" in md
    assert md.index("Diederik P. Kingma") > abroad_idx
    # institutions + companies + exclusions
    assert "### Research institutions" in md
    assert "University of Amsterdam" in md
    assert "_none in window_" in md  # Microsoft Research has no in-window papers
    assert "### Companies (reference)" in md
    assert "Weaviate" in md
    assert "Reference only" in md
    assert "Wonderful" in md  # exclusions note


def test_kingma_in_abroad_bucket_not_nl():
    res = _result_with_watchlist()
    # NL people list never contains the abroad name
    assert all(p.name != "Diederik P. Kingma" for p in res.watchlist.people)
    assert res.watchlist.people_abroad[0].name == "Diederik P. Kingma"


def test_json_includes_watchlist_object():
    import json
    js = report.render_json(_result_with_watchlist())
    data = json.loads(js)
    assert "watchlist" in data
    names = [p["name"] for p in data["watchlist"]["people"]]
    assert "Max Welling" in names and "Diederik P. Kingma" not in names
    assert data["watchlist"]["people_abroad"][0]["name"] == "Diederik P. Kingma"
    assert any(c["name"] == "Weaviate" for c in data["watchlist"]["companies"])
    assert data["watchlist"]["exclusions_note"]


def test_no_watchlist_omits_section():
    res = _result_with_watchlist()
    res.watchlist = None
    md = report.render_markdown(res)
    assert "Netherlands GenAI map" not in md
    import json
    data = json.loads(report.render_json(res))
    assert "watchlist" not in data


def test_unresolved_person_rendered_as_such():
    res = _result_with_watchlist()
    res.watchlist.people = [ResolvedPerson(name="Ghost", status="unresolved")]
    md = report.render_markdown(res)
    assert "Ghost" in md and "unresolved" in md


def test_config_people_have_verify_flags():
    by_name = {p["name"]: p for p in wl_config.WATCHLIST_PEOPLE}
    assert by_name["Tim Salimans"]["verify"] is True
    assert by_name["Emiel Hoogeboom"]["verify"] is True
    assert by_name["Max Welling"]["verify"] is False
    # Kingma lives in the abroad list, never the NL list
    assert "Diederik P. Kingma" not in by_name
    assert wl_config.WATCHLIST_PEOPLE_ABROAD[0]["name"] == "Diederik P. Kingma"
