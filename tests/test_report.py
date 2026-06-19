import json

from labpapers import report
from labpapers.model import Author, Paper, PaperAuthor
from labpapers.pipeline import Result


def _build_result():
    giant = PaperAuthor(name="Giant", openalex_id="A1", cited_by_count=50000,
                        h_index=90, prominence_known=True, is_giant=True)
    small = PaperAuthor(name="Small", openalex_id="A2", cited_by_count=10,
                        h_index=2, prominence_known=True)
    p1 = Paper(
        title="Giant Paper", arxiv_id="2606.0001", date="2026-06-10",
        authors=[giant, small], labs_matched=["openai"],
        source_engines=["openalex-institutions"], abs_url="https://arxiv.org/abs/2606.0001",
        primary_category="cs.CL", abstract="A reasoning model.",
        max_author_cited_by=50000, sum_author_cited_by=50010,
        has_giant_author=True, prominence_available=True,
    )
    p2 = Paper(
        title="DeepSeek HTML Paper", arxiv_id="2606.0002", date="2026-06-12",
        authors=[PaperAuthor(name="Mystery")], labs_matched=["deepseek"],
        source_engines=["arxiv", "affiliation:html"],
        affiliation_evidence=["DeepSeek-AI, Beijing"],
        abs_url="https://arxiv.org/abs/2606.0002", resolved_via="html",
        prominence_available=False,
    )
    people_overall = [
        Author(openalex_id="A1", name="Giant", cited_by_count=50000, h_index=90,
               lab="openai", is_giant=True),
        Author(openalex_id="A2", name="Small", cited_by_count=10, h_index=2,
               lab="openai"),
    ]
    return Result(
        papers=[p1, p2],
        people_overall=people_overall,
        people_by_lab={"openai": people_overall, "deepseek": []},
        from_date="2026-06-12",
        to_date="2026-06-19",
        labs=["openai", "deepseek"],
        per_lab_counts={"openai": 1, "deepseek": 1},
    )


def test_markdown_leads_with_key_people_then_papers():
    md = report.render_markdown(_build_result(), generated_at="2026-06-19T00:00:00")
    people_idx = md.index("## Key People")
    papers_idx = md.index("## Papers by lab")
    assert people_idx < papers_idx
    # overall ranking is non-empty
    assert "### Overall" in md
    assert "Giant" in md


def test_markdown_marks_giants_and_groups_by_lab():
    md = report.render_markdown(_build_result())
    assert "\U0001F31F" in md  # star somewhere
    assert "### OpenAI" in md
    assert "### DeepSeek (1)" in md
    assert "giant-author paper" in md
    # HTML-only paper carries the prominence-unavailable note
    assert "prominence unavailable" in md
    assert "DeepSeek-AI, Beijing" in md


def test_json_is_valid_and_complete():
    js = report.render_json(_build_result(), generated_at="2026-06-19T00:00:00")
    data = json.loads(js)
    assert data["window"] == {"from": "2026-06-12", "to": "2026-06-19"}
    assert len(data["papers"]) == 2
    assert data["per_lab_counts"]["openai"] == 1
    assert data["people_overall"][0]["name"] == "Giant"
    assert data["papers"][0]["impact_summary"]


def test_write_reports_creates_files(tmp_path):
    paths = report.write_reports(
        _build_result(), str(tmp_path), fmt="both", generated_at="2026-06-19T00:00:00"
    )
    assert len(paths) == 2
    names = sorted(p.split("/")[-1] for p in paths)
    assert names == ["labpapers_2026-06-19_7d.json", "labpapers_2026-06-19_7d.md"]
    for p in paths:
        with open(p) as fh:
            assert fh.read().strip()
