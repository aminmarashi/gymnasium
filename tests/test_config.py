from labpapers import config


def test_affiliation_match_anthropic():
    matched = config.match_labs_by_affiliation([
        "Anthropic, San Francisco",
        "Some University",
    ])
    assert "anthropic" in matched
    assert matched["anthropic"] == ["Anthropic, San Francisco"]


def test_affiliation_match_deepseek_and_zhipu():
    matched = config.match_labs_by_affiliation([
        "DeepSeek-AI, Beijing, China",
        "Zhipu AI",
        "Z.ai Inc",
    ])
    assert "deepseek" in matched
    assert "zhipu" in matched


def test_affiliation_match_meta_variants():
    matched = config.match_labs_by_affiliation([
        "FAIR at Meta",
        "Facebook AI Research",
    ])
    assert "meta" in matched


def test_affiliation_no_false_positive_in_abstract_like_text():
    # plain words that are not lab names should not match anything
    matched = config.match_labs_by_affiliation([
        "Department of Computer Science, MIT",
    ])
    assert matched == {}


def test_affiliation_only_filter_restricts_labs():
    matched = config.match_labs_by_affiliation(
        ["OpenAI", "Anthropic"], only=["anthropic"]
    )
    assert "anthropic" in matched
    assert "openai" not in matched


def test_match_labs_by_institution_normalizes_urls():
    matched = config.match_labs_by_institution([
        "https://openalex.org/I4210161460",  # OpenAI
        "i4401726915",  # Zhipu, lowercase
    ])
    assert matched == {"openai", "zhipu"}


def test_selected_labs_preserves_order():
    sel = config.selected_labs(["deepseek", "anthropic"])
    # LABS order is anthropic ... deepseek, so anthropic comes first
    assert list(sel.keys()) == ["anthropic", "deepseek"]


def test_keyword_filter():
    assert config.has_genai_keyword("A new large language model for reasoning")
    assert config.has_genai_keyword("Diffusion-based image generation")
    assert not config.has_genai_keyword("Sparse grid finite element solver")


def test_keyword_filter_word_boundary_no_substring_false_positives():
    # "rag"/"rl"/"moe" must not match inside unrelated words.
    assert not config.has_genai_keyword("Digital twins for storage racks")
    assert not config.has_genai_keyword("PM2.5 regional air-quality sensors")
    assert not config.has_genai_keyword("30+ Years of Malicious Cryptography")
    assert not config.has_genai_keyword("Modelling urban congestion in the world")


def test_keyword_filter_still_matches_acronyms_and_plurals():
    assert config.has_genai_keyword("Retrieval-augmented generation (RAG) for QA")
    assert config.has_genai_keyword("A study of LLM reasoning")
    assert config.has_genai_keyword("Mixture-of-experts (MoE) routing")
    # plurals/morphology of real words still pass
    assert config.has_genai_keyword("Coordinating multiple LLM agents")
    assert config.has_genai_keyword("Sentence embeddings for retrieval")


def test_ambiguous_diffusion_does_not_leak_non_genai_paper():
    # The origins-of-life catalytic-polymer paper that leaked into the 30-day
    # report: its only "GenAI" hit was the bare word "diffusion" ("slower
    # diffusion"). With no GenAI phrase and no core keyword, it must NOT pass.
    title = ("Conditions Enabling the Persistence of Cooperating Synthetase, "
             "Ligase, and Mutation-Inhibitor Catalytic Polymers")
    abstract = (
        "In origins-of-life research, a key challenge is to explain the "
        "emergence of polymers of sufficient length to confer complex functions "
        "needed for genetic inheritance. The persistence of cooperative "
        "synthetase-ligase systems is facilitated by both intrinsic factors "
        "(shorter length, higher catalytic efficiency) and factors that promote "
        "multilevel-selection (compartmentalization, slower diffusion)."
    )
    assert not config.has_genai_keyword(title + " " + abstract)


def test_ambiguous_words_require_phrase_or_cooccurring_core_keyword():
    # Bare ambiguous words alone are NOT a GenAI signal ...
    assert not config.has_genai_keyword("slower diffusion in a polymer melt")
    assert not config.has_genai_keyword("a three-phase electrical transformer")
    assert not config.has_genai_keyword("next generation power grid planning")
    assert not config.has_genai_keyword("multiple sequence alignment of proteins")
    # ... but a specific GenAI phrase qualifies ...
    assert config.has_genai_keyword("a latent diffusion model for images")
    assert config.has_genai_keyword("a transformer architecture for translation")
    assert config.has_genai_keyword("controllable text generation")
    assert config.has_genai_keyword("preference alignment for safer assistants")
    # ... and so does co-occurrence with a core keyword (here: language model).
    assert config.has_genai_keyword(
        "We use diffusion to pretrain a large language model"
    )


def test_bare_instruction_does_not_leak_machine_instructions():
    # "instruction" used to match CPU/assembly "instructions" -- a pre-disassembly
    # binary-analysis paper leaked on it. Only GenAI instruction-* phrases count.
    assert not config.has_genai_keyword(
        "Pre-disassembly static binary analysis over each x86 instruction"
    )
    assert config.has_genai_keyword("instruction tuning improves zero-shot transfer")
    assert config.has_genai_keyword("an instruction-following assistant")


def test_zai_regex_does_not_match_unrelated_orgs():
    matched = config.match_labs_by_affiliation([
        "Feedzai, Lisbon",
        "effectz.ai Inc",
    ])
    assert "zhipu" not in matched


def test_zai_regex_matches_real_zai_and_zhipu():
    matched = config.match_labs_by_affiliation([
        "Z.AI", "Zhipu AI", "ZAI Research",
    ])
    assert "zhipu" in matched


def test_persona_author_detection():
    personas = [
        "Ace (Claude Opus, Anthropic)",
        "Nova (GPT-5.x, OpenAI)",
        "Anthropic) Ace (Claude",
        "Anthropic - second instance) Tide (Claude 4.7",
        "Google DeepMind) Lumen (Gemini",
        "Grok (xAI)",
        "Kairo (DeepSeek)",
        "OpenAI) Cae (GPT-4o",
        # bare versioned model ids and brand-name "authors" (no parentheses)
        "Claude Sonnet 4.6",
        "Claude Sonnet",
        "ChatGPT 5.3",
        "Gemini 3",
        "DeepSeek",
        "Anthropic",
    ]
    for name in personas:
        assert config.is_persona_author(name), name
    # real human names (even a single "Claude"/"Nova" token) are not personas
    for name in ["Demis Hassabis", "Jared Kaplan", "Claude Sammut",
                 "Claude Berrou", "Nova Lee", "Paul Werbos"]:
        assert not config.is_persona_author(name), name


def test_persona_author_detected_by_junk_affiliation():
    # a multi-lab enumeration in one string betrays a junk deposit
    assert config.is_persona_author(
        "Real Name", ["Anthropic, OpenAI, Google DeepMind, DeepSeek"]
    )
    assert not config.is_persona_author("Real Name", ["Anthropic AI"])


def test_affiliation_match_skips_persona_and_multilab_strings():
    matched = config.match_labs_by_affiliation([
        "Ace (Claude Opus, Anthropic)",            # lab embedded in a persona
        "Anthropic, OpenAI, Google DeepMind",       # multi-lab enumeration
        "Anthropic",                                # one clean standalone hit
    ])
    assert matched.get("anthropic") == ["Anthropic"]
    assert "openai" not in matched
    assert "google" not in matched


def test_anthropic_and_deepseek_have_no_institution_ids():
    assert config.LABS["anthropic"].openalex_institution_ids == []
    assert config.LABS["deepseek"].openalex_institution_ids == []
