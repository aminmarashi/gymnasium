from labpapers.sources import openalex


def test_short_id():
    assert openalex.short_id("https://openalex.org/A123") == "A123"
    assert openalex.short_id("A123") == "A123"
    assert openalex.short_id(None) is None


def test_reconstruct_abstract_orders_by_position():
    inv = {"Hello": [0, 3], "world": [1], "again": [2]}
    assert openalex.reconstruct_abstract(inv) == "Hello world again Hello"


def test_reconstruct_abstract_empty():
    assert openalex.reconstruct_abstract(None) == ""
    assert openalex.reconstruct_abstract({}) == ""


def test_arxiv_id_from_doi():
    assert openalex.arxiv_id_from_doi(
        "https://doi.org/10.48550/arXiv.2606.01234"
    ) == "2606.01234"
    assert openalex.arxiv_id_from_doi("10.48550/arxiv.2401.00001v3") == "2401.00001"
    assert openalex.arxiv_id_from_doi("10.1000/not-arxiv") is None
    assert openalex.arxiv_id_from_doi(None) is None


def test_normalize_work(fixture):
    work = fixture("openalex_work.json")
    paper = openalex.normalize_work(work)
    assert paper.title.startswith("Scaling Instruction-Tuned")
    assert paper.arxiv_id == "2606.01234"
    assert paper.date == "2026-06-17"
    assert paper.cited_by_count == 3
    assert paper.abstract == "We study reasoning in language models."
    assert len(paper.authors) == 2

    ada = paper.authors[0]
    assert ada.openalex_id == "A5000000001"
    assert ada.institution_ids == ["I4210161460"]
    assert ada.raw_affiliation_strings == ["OpenAI, San Francisco, CA"]

    bob = paper.authors[1]
    # affiliation provided via the alternate `affiliations` list shape
    assert bob.raw_affiliation_strings == ["DeepSeek-AI, Beijing, China"]


def test_author_is_cs_ai_by_topic_field():
    cs = {"topics": [{"field": {"display_name": "Computer Science"}}]}
    assert openalex.author_is_cs_ai(cs)


def test_author_is_cs_ai_by_subfield_hint():
    ml = {"topics": [
        {"field": {"display_name": "Mathematics"},
         "subfield": {"display_name": "Artificial Intelligence"}},
    ]}
    assert openalex.author_is_cs_ai(ml)


def test_author_is_cs_ai_rejects_non_cs():
    urologist = {
        "topics": [
            {"field": {"display_name": "Medicine"},
             "subfield": {"display_name": "Urology"}},
        ],
        "x_concepts": [{"display_name": "Medicine", "score": 95}],
    }
    assert not openalex.author_is_cs_ai(urologist)
    # no topical signal at all -> treated as non-CS
    assert not openalex.author_is_cs_ai({})


def test_author_is_cs_ai_concept_fallback_threshold():
    weak = {"x_concepts": [{"display_name": "Computer science", "score": 5}]}
    assert not openalex.author_is_cs_ai(weak)
    strong = {"x_concepts": [{"display_name": "Computer science", "score": 60}]}
    assert openalex.author_is_cs_ai(strong)
