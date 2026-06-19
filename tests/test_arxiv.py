from labpapers.sources import arxiv


def test_parse_feed_basic(fixture):
    text = fixture("arxiv_feed.xml")
    papers = arxiv.parse_feed(text)
    assert len(papers) == 2

    p = papers[0]
    assert p.arxiv_id == "2606.01234"  # version stripped
    assert p.title == "Scaling Instruction-Tuned Language Models for Reasoning"
    assert p.date == "2026-06-17"
    assert p.primary_category == "cs.CL"
    assert "cs.LG" in p.categories
    assert p.abs_url == "http://arxiv.org/abs/2606.01234v2"
    assert p.pdf_url == "http://arxiv.org/pdf/2606.01234v2"
    assert p.source_engines == ["arxiv"]
    assert [a.name for a in p.authors] == ["Ada Researcher", "Bob Scientist"]
    # journal DOI present in the feed should be preferred
    assert p.doi == "10.1000/journal.2026.42"


def test_parse_feed_builds_arxiv_doi_when_missing(fixture):
    text = fixture("arxiv_feed.xml")
    papers = arxiv.parse_feed(text)
    second = papers[1]
    # no arxiv:doi in feed -> deterministic arXiv DOI
    assert second.doi == "10.48550/arXiv.2606.05678"


def test_versionless():
    assert arxiv._versionless("http://arxiv.org/abs/2606.01234v2") == "2606.01234"
    assert arxiv._versionless("2606.01234") == "2606.01234"
