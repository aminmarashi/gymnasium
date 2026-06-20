from labrepos import config
from labrepos.model import Repo


def _repo(name="", description="", topics=None, language=None):
    return Repo(
        full_name="o/" + (name or "r"),
        name=name,
        description=description,
        topics=topics or [],
        language=language,
    )


# --- KEEP cases ------------------------------------------------------------
def test_keep_structured_topic():
    # A decisively-GenAI GitHub topic is a structural KEEP.
    r = _repo(name="cool-thing", description="", topics=["llm", "agentic"])
    assert config.classify_topic(r) == config.KEEP


def test_keep_unknown_topic_but_keyword():
    # No structured topic, but the description carries an unambiguous GenAI
    # keyword -> UNKNOWN structurally, but has_genai_keyword rescues it.
    r = _repo(name="router", description="A retrieval-augmented LLM router.")
    assert config.classify_topic(r) == config.UNKNOWN
    assert config.has_genai_keyword(r.description) is True


def test_keep_ambiguous_phrase():
    assert config.has_genai_keyword("a stable diffusion image generator") is True
    assert config.has_genai_keyword("an AI agent framework") is True


# --- broad/non-GenAI topics must NOT structurally keep ---------------------
def test_bare_machine_learning_topic_not_kept():
    # A classic-ML repo tagged only 'machine-learning', with no GenAI signal,
    # must NOT pass on that broad topic alone (would let broad orgs monopolize).
    r = _repo(
        name="xgboost-utils",
        description="Gradient boosting helpers for tabular data.",
        topics=["machine-learning"],
        language="Python",
    )
    assert config.classify_topic(r) == config.UNKNOWN
    assert config.has_genai_keyword(config._repo_text(r)) is False


def test_bare_deep_learning_topic_not_kept():
    # 'deep-learning' alone (classic CV/infra) is no longer a structural keep.
    r = _repo(
        name="resnet-trainer",
        description="Train convolutional image classifiers.",
        topics=["deep-learning", "computer-vision"],
        language="Python",
    )
    assert config.classify_topic(r) == config.UNKNOWN
    assert config.has_genai_keyword(config._repo_text(r)) is False


def test_genai_topic_still_kept_alongside_broad():
    # A genuine GenAI repo still keeps: a specific topic (llm) wins even when a
    # broad topic (machine-learning) is also present.
    r = _repo(
        name="agent-runtime",
        description="Runtime for LLM agents.",
        topics=["machine-learning", "llm"],
    )
    assert config.classify_topic(r) == config.KEEP


# --- EXCLUDE cases ---------------------------------------------------------
def test_exclude_topic_wins_over_keyword():
    # Even with an LLM keyword, an excluding topic wins.
    r = _repo(name="site", description="my llm blog", topics=["blog", "jekyll"])
    assert config.classify_topic(r) == config.EXCLUDE


def test_exclude_keyword_backstop():
    r = _repo(name="dotfiles", description="My personal dotfiles and configs.")
    assert config.classify_topic(r) == config.EXCLUDE


# --- bare-ambiguous false positives must NOT keep --------------------------
def test_bare_diffusion_not_kept():
    # Graphics / thermal "diffusion" is NOT a generative diffusion model.
    r = _repo(
        name="heat-diffusion-solver",
        description="A finite-element solver for thermal diffusion simulation.",
        topics=["physics", "simulation"],
        language="C++",
    )
    assert config.classify_topic(r) == config.UNKNOWN
    assert config.has_genai_keyword(config._repo_text(r)) is False


def test_bare_transformer_not_kept():
    # Electrical transformer, not the architecture.
    r = _repo(
        name="power-transformer-monitor",
        description="Monitoring of electrical distribution transformers.",
        topics=["iot"],
        language="C",
    )
    assert config.classify_topic(r) == config.UNKNOWN
    assert config.has_genai_keyword(config._repo_text(r)) is False


def test_bare_agent_not_kept():
    # HTTP user-agent parsing, not an AI agent.
    r = _repo(
        name="user-agent-parser",
        description="Parse HTTP user agent strings quickly.",
        topics=["http"],
        language="Go",
    )
    assert config.classify_topic(r) == config.UNKNOWN
    assert config.has_genai_keyword(config._repo_text(r)) is False


# --- giant / org maps ------------------------------------------------------
def test_github_is_its_own_giant():
    assert "github" in config.GIANTS
    assert "github" not in config.GIANTS["microsoft"].orgs
    assert config.giant_for_org("github") == "github"
    assert config.giant_for_org("microsoft") == "microsoft"


def test_replit_and_jetbrains_selectable():
    for key in ("replit", "jetbrains"):
        assert key in config.GIANTS
        sel = config.selected_giants([key])
        assert list(sel.keys()) == [key]


def test_org_to_giant_resolves():
    assert config.giant_for_org("facebookresearch") == "meta"
    assert config.giant_for_org("google-deepmind") == "google"
    assert config.giant_for_org("anysphere") == "cursor"
    assert config.giant_for_org("anomalyco") == "opencode"
    assert config.giant_for_org("aaif-goose") == "goose"


def test_families():
    assert "anthropic" in config.giants_for_family("lab")
    assert "cline" in config.giants_for_family("coding")


def test_selected_giants_empty_for_bad_key():
    assert list(config.selected_giants(["not-a-giant"]).keys()) == []
