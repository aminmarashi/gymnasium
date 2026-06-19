from labpapers import config
from labpapers.model import PaperAuthor
from labpapers.sources import affiliations


def test_collective_author_lab_mapping():
    assert config.collective_author_lab("DeepSeek-AI") == "deepseek"
    assert config.collective_author_lab("deepseek-ai") == "deepseek"
    assert config.collective_author_lab("Zhipu AI") == "zhipu"
    assert config.collective_author_lab("GLM Team") == "zhipu"
    assert config.collective_author_lab("DeepSeek") is None  # bare brand
    assert config.collective_author_lab("Jane Researcher") is None


def test_collective_author_is_not_persona():
    # the collective byline is a positive lab signal, NOT persona junk ...
    assert config.is_persona_author("DeepSeek-AI") is False
    assert config.is_persona_author("GLM Team") is False
    # ... while the bare brand name remains persona junk
    assert config.is_persona_author("DeepSeek") is True


def test_persona_junk_still_dropped_after_collective_fix():
    # regression guard: the collective fix must not weaken persona detection
    for name in ["Kairo (DeepSeek)", "Ace (Claude Opus, Anthropic)",
                 "Anthropic) Ace (Claude", "Claude Sonnet 4.6", "Claude Sonnet",
                 "Anthropic"]:
        assert config.is_persona_author(name), name
    # multi-lab enumeration in one affiliation string still flags the author
    assert config.is_persona_author(
        "Real Name", ["Anthropic, OpenAI, Google DeepMind, DeepSeek"]
    )


def test_labs_from_authors_credits_deepseek_collective():
    authors = [
        PaperAuthor(name="DeepSeek-AI"),                 # collective byline
        PaperAuthor(name="Aixin Liu"),                   # empty affiliation
        PaperAuthor(name="Bingxuan Wang"),               # empty affiliation
    ]
    labs, evidence = affiliations.labs_from_authors(authors, only=None)
    assert labs == {"deepseek"}
    assert "DeepSeek-AI" in evidence


def test_labs_from_authors_respects_only_filter():
    authors = [PaperAuthor(name="DeepSeek-AI")]
    labs, _ = affiliations.labs_from_authors(authors, only=["anthropic"])
    assert labs == set()  # deepseek not in the requested labs


def test_deepseek_v32_record_detected(fixture):
    work = fixture("openalex_deepseek_v32.json")
    labs, evidence, authors = affiliations._labs_from_work(work, only=None)
    assert labs == ["deepseek"]
    assert "DeepSeek-AI" in evidence
    # all three authorships (collective + two humans) are kept so the human
    # authors can still contribute OpenAlex ids for prominence
    assert len(authors) == 3
