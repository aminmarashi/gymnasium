from labpapers import config, pipeline
from labpapers.model import Author, Paper, PaperAuthor
from labpapers.sources.base import LabSource


def _paper(**kw):
    return Paper(title=kw.pop("title", "t"), **kw)


class _FakeOpenAlexSource:
    name = "openalex-institution"

    def fetch(self, ctx):
        return [_paper(
            arxiv_id="2606.9", labs_matched=["openai"],
            source_engines=["openalex-institutions"],
            authors=[PaperAuthor(name="Ada", openalex_id="A1")],
        )]


class _FakeSiteSource:
    name = "anthropic-site"

    def fetch(self, ctx):
        return [_paper(
            title="Site post",
            source_url="https://www.anthropic.com/research/foo",
            labs_matched=["anthropic"], source_engines=["anthropic-site"],
        )]


def test_build_sources_anthropic_only_skips_openalex_institution():
    names = [s.name for s in pipeline.build_sources(["anthropic"])]
    assert names == ["arxiv-affiliation", "anthropic-site"]


def test_build_sources_default_includes_all_three_in_order():
    names = [s.name for s in pipeline.build_sources(list(config.LABS.keys()))]
    assert names == ["openalex-institution", "arxiv-affiliation", "anthropic-site"]


def test_labsource_union_dedup_across_openalex_and_site():
    assert isinstance(_FakeOpenAlexSource(), LabSource)
    assert isinstance(_FakeSiteSource(), LabSource)
    collected = _FakeOpenAlexSource().fetch(None) + _FakeSiteSource().fetch(None)
    merged = pipeline.dedup_papers(collected)
    # arxiv-id-keyed and source-url-keyed papers coexist (no false merge)
    assert len(merged) == 2
    assert {lab for p in merged for lab in p.labs_matched} == {"openai", "anthropic"}


def test_dedup_keys_site_papers_by_source_url():
    site_a = _paper(title="X", source_url="https://a.co/research/foo",
                    labs_matched=["anthropic"], source_engines=["anthropic-site"])
    # same url, different title -> still the same paper (deduped by url)
    site_dup = _paper(title="X totally different", source_url="https://a.co/research/foo",
                      labs_matched=["anthropic"], source_engines=["anthropic-site"])
    site_b = _paper(title="Y", source_url="https://a.co/research/bar",
                    labs_matched=["anthropic"], source_engines=["anthropic-site"])
    merged = pipeline.dedup_papers([site_a, site_dup, site_b])
    assert len(merged) == 2


def test_dedup_merges_same_title_across_different_source_urls():
    # Regression: source url is an ADDITIONAL identity, not a replacement for
    # normalized-title dedup. Two OpenAlex/site records for the same paper that
    # carry different urls (and no arxiv id / doi) must still collapse by title.
    a = _paper(title="Scaling Laws for Reward Models",
               source_url="https://openalex.org/W1",
               labs_matched=["openai"], source_engines=["openalex-institutions"])
    b = _paper(title="scaling   laws for reward models",
               source_url="https://arxiv.org/abs/2606.1",
               labs_matched=["deepseek"], source_engines=["arxiv"])
    merged = pipeline.dedup_papers([a, b])
    assert len(merged) == 1
    assert set(merged[0].labs_matched) == {"openai", "deepseek"}


def test_dedup_is_transitive_when_a_paper_bridges_two_records():
    # Regression: a later paper can bridge two already-canonical records -- C's
    # DOI matches A while C's title matches B. Dedup must fold ALL THREE into one
    # record, not stop at the first match and leave B as a duplicate.
    a = _paper(title="Alpha Paper", doi="10.1/x", labs_matched=["openai"])
    b = _paper(title="Bridge Title", labs_matched=["google"])
    c = _paper(title="bridge   title", doi="https://doi.org/10.1/X",
               labs_matched=["meta"])
    merged = pipeline.dedup_papers([a, b, c])
    assert len(merged) == 1
    assert set(merged[0].labs_matched) == {"openai", "google", "meta"}


def test_dedup_merges_when_any_identity_matches():
    # An arxiv-keyed record and a doi-keyed record for the same paper share only
    # the normalized title -> they must merge (title is always an identity).
    a = _paper(title="Same Paper Title", arxiv_id="2606.5", labs_matched=["meta"])
    b = _paper(title="same paper title", doi="10.1/x", labs_matched=["google"])
    merged = pipeline.dedup_papers([a, b])
    assert len(merged) == 1
    assert set(merged[0].labs_matched) == {"meta", "google"}


def test_topic_filter_cs_cl_always_passes():
    p = _paper(primary_category="cs.CL", categories=["cs.CL"], abstract="boring")
    assert pipeline.topic_filter(p, require_keyword=True)


def test_topic_filter_requires_keyword_for_other_categories():
    p = _paper(primary_category="cs.CV", categories=["cs.CV"], abstract="cats")
    assert not pipeline.topic_filter(p, require_keyword=True)
    p2 = _paper(
        primary_category="cs.CV", categories=["cs.CV"],
        abstract="a multimodal diffusion model",
    )
    assert pipeline.topic_filter(p2, require_keyword=True)


def test_topic_filter_off_passes_everything():
    p = _paper(primary_category="math.NA", categories=["math.NA"], abstract="grid")
    assert pipeline.topic_filter(p, require_keyword=False)


def test_dedup_by_arxiv_id_merges_labs_and_engines():
    a = _paper(
        arxiv_id="2606.01234", labs_matched=["openai"],
        source_engines=["openalex-institutions"], cited_by_count=2,
        authors=[PaperAuthor(name="Ada", openalex_id="A1")],
    )
    b = _paper(
        arxiv_id="2606.01234", labs_matched=["deepseek"],
        source_engines=["arxiv"], cited_by_count=5,
        affiliation_evidence=["DeepSeek-AI"],
        authors=[PaperAuthor(name="Ada", openalex_id="A1"),
                 PaperAuthor(name="Bob", openalex_id="A2")],
    )
    merged = pipeline.dedup_papers([a, b])
    assert len(merged) == 1
    m = merged[0]
    assert set(m.labs_matched) == {"openai", "deepseek"}
    assert set(m.source_engines) == {"openalex-institutions", "arxiv"}
    assert m.cited_by_count == 5  # max
    assert m.affiliation_evidence == ["DeepSeek-AI"]
    # Ada deduped by openalex id, Bob added -> 2 authors total
    assert {x.openalex_id for x in m.authors} == {"A1", "A2"}


def test_dedup_by_doi_then_title():
    a = _paper(doi="10.1/x", title="Same Title")
    b = _paper(doi="https://doi.org/10.1/X", title="other")
    merged = pipeline.dedup_papers([a, b])
    assert len(merged) == 1  # DOI normalized -> same paper

    c = _paper(title="Hello World!")
    d = _paper(title="hello   world")
    merged2 = pipeline.dedup_papers([c, d])
    assert len(merged2) == 1  # normalized title -> same paper


def test_attach_prominence_computes_impact_and_giant_flag():
    giant = Author(openalex_id="A1", name="Giant", cited_by_count=50000, h_index=90)
    small = Author(openalex_id="A2", name="Small", cited_by_count=10, h_index=2)
    prominence = {"A1": giant, "A2": small}

    p_giant = _paper(
        title="big", date="2026-06-10",
        authors=[PaperAuthor(name="Giant", openalex_id="A1"),
                 PaperAuthor(name="Small", openalex_id="A2")],
    )
    p_small = _paper(
        title="small", date="2026-06-12",
        authors=[PaperAuthor(name="Small", openalex_id="A2")],
    )
    # HTML-only paper: no author ids -> prominence unavailable, signal 0
    p_html = _paper(
        title="html only", date="2026-06-18",
        authors=[PaperAuthor(name="Mystery")],
    )

    ranked = pipeline.attach_prominence([p_small, p_html, p_giant], prominence)

    # giant paper sorts first (max author cited_by dominates)
    assert ranked[0].title == "big"
    assert ranked[0].max_author_cited_by == 50000
    assert ranked[0].sum_author_cited_by == 50010
    assert ranked[0].has_giant_author is True
    assert ranked[0].prominence_available is True

    # html-only paper sorts last with zero signal and unavailable prominence
    assert ranked[-1].title == "html only"
    assert ranked[-1].max_author_cited_by == 0
    assert ranked[-1].prominence_available is False
    assert "prominence unavailable" in ranked[-1].impact_summary()

    # author-level giant flag set on the enriched author ref
    assert any(a.is_giant for a in ranked[0].authors)


def test_giant_threshold_respects_hindex():
    hi = Author(openalex_id="A3", name="H", cited_by_count=100, h_index=45)
    p = _paper(authors=[PaperAuthor(name="H", openalex_id="A3")])
    pipeline.attach_prominence([p], {"A3": hi})
    assert p.has_giant_author is True


def test_papers_for_lab_dedupes_same_title_within_section():
    # Same title, different arXiv ids -> only the first (highest-signal) is kept.
    a = _paper(title="Preference Dissociation", arxiv_id="2606.0001",
               labs_matched=["anthropic"], max_author_cited_by=100)
    b = _paper(title="preference   dissociation", arxiv_id="2606.0002",
               labs_matched=["anthropic"], max_author_cited_by=5)
    other = _paper(title="Other Paper", arxiv_id="2606.0003",
                   labs_matched=["anthropic"])
    lab_papers = pipeline.papers_for_lab([a, b, other], "anthropic")
    assert [p.arxiv_id for p in lab_papers] == ["2606.0001", "2606.0003"]


def test_papers_for_lab_keeps_same_title_across_different_labs():
    a = _paper(title="Scaling Laws", arxiv_id="2606.0001", labs_matched=["openai"])
    b = _paper(title="Scaling Laws", arxiv_id="2606.0002", labs_matched=["google"])
    assert len(pipeline.papers_for_lab([a, b], "openai")) == 1
    assert len(pipeline.papers_for_lab([a, b], "google")) == 1
