"""Static configuration: labs, institution ids, affiliation regexes, topic
keywords, and giant thresholds.

All values here were grounded against the live OpenAlex and arXiv APIs while
the plan was written:

- OpenAlex tags institutions cleanly for OpenAI, Meta, Google (incl. Google
  DeepMind), and weakly for Zhipu.
- OpenAlex reports 0 works for Anthropic (I4387930290) and DeepSeek
  (I4405257960), and its raw-affiliation text search for those names is
  junk-polluted -- so those two labs have NO usable institution id and are
  resolved purely via the arXiv affiliation path (DOI -> raw affiliation
  strings, then arxiv.org/html fallback).
"""

from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Pattern, Set


@dataclass(frozen=True)
class LabConfig:
    """Configuration for a single lab."""

    key: str
    display_name: str
    openalex_institution_ids: List[str] = field(default_factory=list)
    affiliation_patterns: List[str] = field(default_factory=list)

    def compiled_patterns(self) -> List[Pattern[str]]:
        return [re.compile(p, re.IGNORECASE) for p in self.affiliation_patterns]


# Ordered so report sections appear in a stable, intentional order.
LABS: "OrderedDict[str, LabConfig]" = OrderedDict()


def _add(lab: LabConfig) -> None:
    LABS[lab.key] = lab


_add(LabConfig(
    key="anthropic",
    display_name="Anthropic",
    openalex_institution_ids=[],
    affiliation_patterns=[r"\bAnthropic\b"],
))
_add(LabConfig(
    key="meta",
    display_name="Meta",
    openalex_institution_ids=["I4210114444", "I2252078561", "I4210111288"],
    affiliation_patterns=[
        r"\bMeta AI\b",
        r"\bFAIR\b",
        r"Facebook AI",
        r"Meta Platforms",
        r"GenAI, Meta",
    ],
))
_add(LabConfig(
    key="google",
    display_name="Google (incl. DeepMind)",
    openalex_institution_ids=[
        "I1291425158",
        "I4210090411",
        "I4210113297",
        "I4210148186",
        "I4210100430",
        "I4210117425",
    ],
    affiliation_patterns=[
        r"\bGoogle\b",
        r"DeepMind",
        r"Google Research",
        r"Google Brain",
    ],
))
_add(LabConfig(
    key="openai",
    display_name="OpenAI",
    openalex_institution_ids=["I4210161460"],
    affiliation_patterns=[r"\bOpenAI\b"],
))
_add(LabConfig(
    key="zhipu",
    display_name="Z.AI (Zhipu AI)",
    openalex_institution_ids=["I4401726915"],
    # A leading word boundary keeps "Z.AI"/"ZAI" from matching the *tails* of
    # unrelated names such as "Feedzai" or the domain "effectz.ai".
    affiliation_patterns=[r"\bZhipu", r"\bZ\.?AI\b"],
))
_add(LabConfig(
    key="deepseek",
    display_name="DeepSeek",
    openalex_institution_ids=[],
    affiliation_patterns=[r"DeepSeek"],
))


# Per-lab source pipeline: which named sources contribute papers for each lab.
# The pipeline takes the union of these names over the selected labs and runs
# each source once. The default reproduces the original two-engine behavior
# (OpenAlex institution works + arXiv affiliation resolution) and adds the
# Anthropic publications-site source so Anthropic is covered directly.
SOURCES: "OrderedDict[str, List[str]]" = OrderedDict([
    ("anthropic", ["arxiv-affiliation", "anthropic-site"]),
    ("meta", ["openalex-institution", "arxiv-affiliation"]),
    ("google", ["openalex-institution", "arxiv-affiliation"]),
    ("openai", ["openalex-institution", "arxiv-affiliation"]),
    ("zhipu", ["openalex-institution", "arxiv-affiliation"]),
    ("deepseek", ["arxiv-affiliation"]),
])


def sources_for_labs(lab_keys: Iterable[str]) -> List[str]:
    """Ordered, de-duplicated list of source names covering the given labs."""

    wanted: List[str] = []
    for key in lab_keys:
        for name in SOURCES.get(key, []):
            if name not in wanted:
                wanted.append(name)
    return wanted


# arXiv categories that make up the GenAI candidate pool.
DEFAULT_CATEGORIES: List[str] = [
    "cs.CL",
    "cs.LG",
    "cs.AI",
    "cs.CV",
    "cs.MA",
    "cs.IR",
    "stat.ML",
]

# A category that ALWAYS passes the topic filter (no keyword required).
ALWAYS_PASS_CATEGORIES: Set[str] = {"cs.CL"}

# GenAI keyword set used to topic-filter the broad candidate pool. Matched
# case-insensitively against title + abstract. These are the *unambiguous* GenAI
# terms: a single hit is enough to keep a paper. Broad single words that also
# carry strong non-ML meanings (physical "diffusion", an electrical
# "transformer", "power generation", sequence "alignment") are NOT here -- they
# live in AMBIGUOUS_KEYWORD_PHRASES and only count inside a GenAI-specific phrase
# or when one of these unambiguous terms co-occurs.
#
# The same care applies to bare ML words that read GenAI but recur across
# classical AI: "agent" (multi-agent RL / game-theoretic social dilemmas) and
# "reasoning" (declarative logic programming, automated theorem proving) are NOT
# here -- a Multi-Agent Reinforcement Learning / Sequential-Social-Dilemmas paper
# leaked on the bare "agent". They are admitted ONLY through the qualified GenAI
# phrases below ("LLM agent", "agentic AI", "tool-using", "reasoning model", ...),
# so the booster never re-admits generic RL / game-theory / logic work.
GENAI_KEYWORDS: List[str] = [
    "language model",
    "large language model",
    "llm",
    "foundation model",
    "generative",
    # agents: only the GenAI-qualified forms, never the bare "agent" (which leaks
    # classical multi-agent RL / game theory). "LLM agent" matches "LLM agents".
    "llm agent",
    "language model agent",
    "ai agent",
    "agentic ai",
    "agentic workflow",
    "agentic system",
    "tool use",
    "tool-use",
    "tool-using",
    "tool using",
    "coding agent",
    "multimodal",
    "vision-language",
    "vision language",
    "rlhf",
    "reinforcement learning from human feedback",
    # reasoning: only GenAI-qualified forms, never the bare "reasoning" (which
    # leaks logic programming / theorem proving). chain-of-thought is below.
    "reasoning model",
    "llm reasoning",
    "reasoning llm",
    # "instruction" alone matched machine-code "instructions" (a binary-analysis
    # paper leaked on it); only the GenAI-specific instruction-* phrases count.
    "instruction-tuning",
    "instruction tuning",
    "instruction-tuned",
    "instruction-following",
    "instruction following",
    "in-context learning",
    "chain-of-thought",
    "chain of thought",
    "retrieval-augmented",
    "retrieval augmented",
    "rag",
    "prompt",
    "fine-tuning",
    "fine tuning",
    "pretraining",
    "pre-training",
    "embedding",
    "text-to-image",
    "text-to-video",
    "speech",
    "mixture-of-experts",
    "mixture of experts",
    "moe",
    "gpt",
    "chatbot",
    "dialogue",
]

# Ambiguous single words that leak non-GenAI papers on their own -- "slower
# diffusion" in an origins-of-life polymer paper, an electrical "transformer",
# "power generation", a bioinformatics sequence "alignment". Each counts as a
# GenAI hit ONLY inside one of these specific phrases, OR when an unambiguous
# GENAI_KEYWORD co-occurs in the same text (see has_genai_keyword, which returns
# True on any core hit first). Phrases get the same word-boundary + optional
# plural treatment as the core keywords.
AMBIGUOUS_KEYWORD_PHRASES: List[str] = [
    # diffusion: generative diffusion models, not physical diffusion
    "diffusion model",
    "diffusion-based",
    "diffusion based",
    "latent diffusion",
    "stable diffusion",
    "diffusion transformer",
    "denoising diffusion",
    "score-based diffusion",
    "diffusion probabilistic",
    "guided diffusion",
    "conditional diffusion",
    "text-to-image diffusion",
    # transformer: the architecture, not electrical transformers
    "transformer model",
    "transformer architecture",
    "transformer-based",
    "transformer based",
    "vision transformer",
    "transformer network",
    "transformer encoder",
    "transformer decoder",
    "decoder-only transformer",
    "pretrained transformer",
    "autoregressive transformer",
    # generation: text/image/etc generation, not power/next generation
    "text generation",
    "image generation",
    "video generation",
    "code generation",
    "language generation",
    "speech generation",
    "audio generation",
    "music generation",
    "data generation",
    "natural language generation",
    "controllable generation",
    "conditional generation",
    "open-ended generation",
    "open ended generation",
    "generation model",
    # alignment: model/AI alignment, not sequence/image alignment
    "ai alignment",
    "model alignment",
    "preference alignment",
    "value alignment",
    "safety alignment",
    "instruction alignment",
    "alignment of language models",
]

# ---------------------------------------------------------------------------
# Structured topic classification -- the PRIMARY GenAI-scope signal.
# ---------------------------------------------------------------------------
# Keyword matching alone leaked non-GenAI papers round after round: a
# Google-affiliated co-author on a protein-folding / traffic-forecasting /
# steel-defect paper still tripped a broad term ("generative",
# "transformer-based") and slipped into the report. The fix replaces the
# keyword-primary filter with a STRUCTURED classifier:
#
#   * OpenAlex works are classified on their primary_topic field/subfield.
#   * arXiv works are gated on their primary category.
#   * A small EXCLUDE set of application-domain fields / arXiv categories /
#     domain phrases ALWAYS wins, overriding any keyword hit.
#   * The GenAI keyword set (has_genai_keyword) is now only a SECONDARY booster
#     for records the structured signal leaves inconclusive.
#
# Scope is STRICT GenAI (LLM / generative / multimodal / agents / NLP / CV /
# IR), not all AI/ML: ML *applied to* another domain (protein folding, traffic,
# steel defects, climate, finance) is out.

# arXiv categories that are in GenAI scope. A work whose PRIMARY category is
# outside this set is excluded (q-bio.*, physics.*, math.*, econ.*, eess.SY,
# q-fin.*, ...). Lower-cased for case-insensitive comparison.
ARXIV_GENAI_CATEGORIES: Set[str] = {
    "cs.cl", "cs.ai", "cs.lg", "cs.cv", "cs.ma", "cs.ir", "eess.as", "stat.ml",
}

# OpenAlex *field* display names that are OUT of GenAI scope. A work whose
# primary_topic field is one of these is EXCLUDED even if a GenAI keyword hits --
# these are exactly the application domains the keyword leaks arrived from. Kept
# to the hard sciences the user ruled out (biology/medicine/health, chemistry,
# materials, physics, earth/environment/energy, mathematics, economics/finance);
# softer fields (social science, psychology) are left to the keyword booster so a
# mis-fielded CS paper is not wrongly dropped.
OPENALEX_EXCLUDE_FIELDS: Set[str] = {
    # life & health sciences
    "medicine", "nursing", "veterinary", "dentistry", "health professions",
    "pharmacology, toxicology and pharmaceutics",
    "biochemistry, genetics and molecular biology",
    "immunology and microbiology", "neuroscience",
    "agricultural and biological sciences",
    # physical sciences other than computer science
    "chemistry", "chemical engineering", "materials science",
    "physics and astronomy", "earth and planetary sciences",
    "environmental science", "energy",
    # quantitative domains the user ruled out
    "mathematics", "economics, econometrics and finance",
}

# OpenAlex *subfield* display names that are out of scope regardless of field.
# Covers the non-CS Engineering subfields and the transportation / civil /
# manufacturing / materials / control application areas the leaks rode in on.
# "Electrical and electronic engineering" is deliberately NOT here -- it hosts
# legitimate speech / signal-processing GenAI work.
OPENALEX_EXCLUDE_SUBFIELDS: Set[str] = {
    "civil and structural engineering", "building and construction",
    "transportation", "automotive engineering", "aerospace engineering",
    "mechanical engineering", "industrial and manufacturing engineering",
    "ocean engineering", "architecture",
    "geotechnical engineering and engineering geology",
    "metals and alloys", "ceramics and composites", "polymers and plastics",
    "biomaterials", "surfaces, coatings and films", "electrochemistry",
    "fuel technology", "nuclear energy and engineering",
    "biomedical engineering", "control and systems engineering",
    "statistics and probability",
    # bio / medical topic subfields that attach to ML-for-science works
    "molecular biology", "structural biology", "biophysics", "genetics",
    "cell biology", "cancer research", "physiology",
}

# Domain phrases that betray a non-GenAI application even when the structured
# field is ambiguous (or absent) or an ML method is merely APPLIED to the domain
# -- e.g. a cs.LG cross-list on protein folding or traffic. A match EXCLUDES.
# This is the cross-domain backstop the design calls for; kept deliberately
# specific so it never fires on a core GenAI paper ("network traffic" is not
# "traffic flow", "embedding space" is not "amino acid"). Matched as a
# case-insensitive substring over title + abstract + primary_topic name.
DOMAIN_EXCLUDE_PHRASES: List[str] = [
    # transportation / traffic / urban
    "traffic prediction", "traffic forecasting", "traffic flow",
    "traffic signal", "real-time traffic", "vehicular", "ride-hailing",
    "bike sharing", "transportation system", "urban mobility",
    # structural / civil / manufacturing / materials
    "steel plate", "steel defect", "weld defect", "fatigue crack",
    "industrial process inspection", "remaining useful life",
    "non-destructive", "structural health monitoring",
    # chemistry / materials / physics
    "condensed matter", "quantum many-body", "first-principles",
    "density functional", "molecular dynamics", "crystal structure",
    "superconduc", "perovskite", "catalytic polymer",
    # biology / medicine / origins-of-life
    "protein folding", "protein structure", "conformational landscape",
    "origins of life", "synthetase", "ligase", "drug discovery",
    "gene expression", "rna sequenc", "dna sequenc", "amino acid",
    "molecular docking",
    # earth / environment / energy
    "air quality", "remote sensing", "weather forecast", "rainfall",
    "groundwater", "photovoltaic", "power grid", "wind speed",
    "seismic", "earthquake",
    # classical-CS domains that leak on ambiguous GenAI words ("reasoning",
    # "agent"): declarative logic programming / databases is not GenAI -- a real
    # GenAI paper never describes its method as "a logic programming language".
    "logic programming language",
]

# CONDITIONAL exclude: privacy / clustering / DP-theory topics that OpenAlex
# files under the coarse CS/"Artificial Intelligence" subfield and that trip the
# keyword booster on incidental phrases ("synthetic data generation", "private
# evolution") despite not being generative AI. A "PE-means: Differentially
# Private k-means Clustering" paper leaked exactly this way (institution scan).
# These EXCLUDE *only* when the work carries no LLM / generative-MODEL-specific
# signal (see GENERATIVE_MODEL_SIGNALS) -- so genuine GenAI privacy work
# ("Differentially Private Image Synthesis", DP fine-tuning of a diffusion
# model, "privacy-preserving alternative ... using generative AI and LLMs")
# still passes. Matched as word-boundary phrases over title + abstract + topic.
CONDITIONAL_EXCLUDE_PHRASES: List[str] = [
    "differential privacy", "differentially private",
    "privacy-preserving", "privacy preserving",
    "private evolution",
    "k-means", "k means", "kmeans",
    "k-median", "k median",
    "clustering algorithm", "data clustering", "spectral clustering",
    "hierarchical clustering", "k-means clustering",
]

# LLM / generative-MODEL-specific signals that RESCUE a conditional-exclude
# paper: the presence of any of these marks the privacy/clustering work as
# genuinely generative (a DP-finetuned diffusion model, LLM privacy auditing,
# image/text synthesis), so the conditional exclude does NOT fire. Deliberately
# narrower than the full GenAI keyword set -- the incidental boosters that leaked
# PE-means ("data generation" / "synthetic data") are NOT here.
GENERATIVE_MODEL_SIGNALS: List[str] = [
    "language model", "large language model", "llm", "foundation model",
    "generative model", "generative ai", "generative adversarial",
    "gan", "vae", "variational autoencoder",
    "diffusion model", "latent diffusion", "stable diffusion",
    "diffusion-based", "denoising diffusion", "score-based diffusion",
    "image synthesis", "image generation", "text-to-image", "text-to-video",
    "video generation", "text generation", "speech synthesis",
    "fine-tuning", "fine tuning", "pretraining", "pre-training",
    "multimodal", "vision-language", "vision language",
    "transformer model", "transformer architecture", "transformer-based",
    "pretrained transformer", "gpt", "chatbot",
    "in-context learning", "instruction tuning", "instruction-tuning", "rlhf",
]

# Giant thresholds: an author is a "giant" when either is exceeded.
GIANT_CITED_BY = 10000
GIANT_HINDEX = 40

# Max length of an affiliation evidence string kept for the report.
EVIDENCE_MAX_LEN = 300

# Pre-compiled (lab_key, patterns) pairs, built once. Used by both the
# affiliation matcher and the multi-lab-enumeration junk check below.
_LAB_PATTERNS: "List[tuple]" = [
    (lab.key, lab.compiled_patterns()) for lab in LABS.values()
]

# Word-boundary keyword regexes. Plain substring matching ("rag" in "storage")
# leaks unrelated papers, so each keyword is anchored on word boundaries with an
# optional trailing plural ("agent" still matches "agents"). This matters most
# for short acronyms (rag, llm, vlm, rl, moe, gpt).
def _compile_keyword_patterns(keywords: List[str]) -> List[Pattern[str]]:
    return [
        re.compile(r"\b" + re.escape(kw) + r"s?\b", re.IGNORECASE)
        for kw in keywords
    ]


_KEYWORD_PATTERNS: List[Pattern[str]] = _compile_keyword_patterns(GENAI_KEYWORDS)

# Same word-boundary treatment for the ambiguous GenAI phrases. Kept separate so
# the bare ambiguous word (e.g. "diffusion") never matches on its own.
_AMBIGUOUS_PHRASE_PATTERNS: List[Pattern[str]] = _compile_keyword_patterns(
    AMBIGUOUS_KEYWORD_PHRASES
)

# Word-boundary patterns for the conditional privacy/clustering exclude and the
# generative-model rescue signals.
_CONDITIONAL_EXCLUDE_PATTERNS: List[Pattern[str]] = _compile_keyword_patterns(
    CONDITIONAL_EXCLUDE_PHRASES
)
_GENERATIVE_MODEL_SIGNAL_PATTERNS: List[Pattern[str]] = _compile_keyword_patterns(
    GENERATIVE_MODEL_SIGNALS
)

# Tokens that betray an LLM "author persona" (a model masquerading as a
# researcher) rather than a real person.
_PERSONA_TOKENS = (
    "Claude", "ChatGPT", "GPT", "Gemini", "DeepSeek", "Grok", "Kimi",
    "Llama", "Mistral", "Nova", "Opus", "Sonnet", "Haiku", "Qwen",
)
_PERSONA_TOKEN_RE = re.compile(
    r"\b(" + "|".join(_PERSONA_TOKENS) + r")\b", re.IGNORECASE
)
# A versioned model id (GPT-5.1, Claude 4.7, Sonnet 4.6, Gemini 3) never names a
# person -- includes the Opus/Sonnet/Haiku tiers so "Claude Sonnet 4.6" is caught.
_MODEL_VERSION_RE = re.compile(
    r"\b(ChatGPT|GPT|Claude|Gemini|Grok|Llama|Mistral|Kimi|Qwen|Opus|Sonnet|Haiku)"
    r"[-\s]?[0-9]",
    re.IGNORECASE,
)
# Display names that are really an org / model brand, not a person (e.g. an
# "author" literally named "DeepSeek"). Matched against the whole stripped name.
_JUNK_NAME_EXACT = {
    "anthropic", "openai", "deepseek", "deepseek-ai", "deepmind",
    "google deepmind", "zhipu", "zhipu ai", "z.ai", "xai",
    "chatgpt", "gpt", "claude", "gemini", "grok",
}

# Exact org-as-author names that are a POSITIVE lab signal, not persona junk.
# Some labs publish papers under a single collective byline (e.g. the
# DeepSeek-V3.2 report lists "DeepSeek-AI" as an author and leaves every human
# author's OpenAlex affiliation empty), so this name is the only lab signal on
# the record. Keys are normalized (lower-cased, whitespace-collapsed) names and
# values are one of the six in-scope lab keys. Note the overlap with
# _JUNK_NAME_EXACT: a collective match takes precedence and is NOT a persona.
ORG_COLLECTIVE_AUTHORS: Dict[str, str] = {
    "deepseek-ai": "deepseek",
    "zhipu ai": "zhipu",
    "glm team": "zhipu",
}

# Anthropic research categories (subjects) are in-scope by default -- an AI
# lab's research listing is GenAI by construction, so the keyword filter is
# bypassed for it. Only clearly non-research subjects are excluded. Matched
# case-insensitively; a post tagged with several subjects is kept if ANY is a
# research subject (so "Policy, Frontier Red Team" stays).
ANTHROPIC_EXCLUDE_CATEGORIES: Set[str] = {"policy"}


def short_institution_ids(ids: Iterable[str]) -> Set[str]:
    """Normalize OpenAlex institution ids (URL or short form) to short form."""

    out: Set[str] = set()
    for i in ids:
        if not i:
            continue
        out.add(i.rstrip("/").rsplit("/", 1)[-1].upper())
    return out


def _institution_lookup() -> Dict[str, str]:
    """Map short institution id -> lab key for every covered lab."""

    lookup: Dict[str, str] = {}
    for lab in LABS.values():
        for short in short_institution_ids(lab.openalex_institution_ids):
            lookup[short] = lab.key
    return lookup


INSTITUTION_TO_LAB: Dict[str, str] = _institution_lookup()


def selected_labs(keys: Iterable[str]) -> "OrderedDict[str, LabConfig]":
    """Return the subset of LABS for the given keys, preserving LABS order."""

    wanted = {k.strip().lower() for k in keys if k and k.strip()}
    return OrderedDict((k, v) for k, v in LABS.items() if k in wanted)


def all_institution_ids(labs: Iterable[LabConfig]) -> List[str]:
    ids: List[str] = []
    for lab in labs:
        ids.extend(lab.openalex_institution_ids)
    return ids


def match_labs_by_institution(
    institution_ids: Iterable[str],
    only: Iterable[str] = None,
) -> Set[str]:
    """Return lab keys matched by OpenAlex institution ids."""

    allowed = set(only) if only is not None else None
    matched: Set[str] = set()
    for short in short_institution_ids(institution_ids):
        lab = INSTITUTION_TO_LAB.get(short)
        if lab and (allowed is None or lab in allowed):
            matched.add(lab)
    return matched


def _count_distinct_labs(s: str) -> int:
    """How many distinct labs' patterns match a single affiliation string."""

    if not s:
        return 0
    hits: Set[str] = set()
    for lab_key, patterns in _LAB_PATTERNS:
        for pat in patterns:
            if pat.search(s):
                hits.add(lab_key)
                break
    return len(hits)


def _affiliation_is_junk(s: str) -> bool:
    """Whether an affiliation string is an AI-persona / multi-lab junk deposit.

    A clean affiliation names exactly one lab as a standalone/leading token. We
    reject strings that (a) enumerate several distinct labs at once or (b) embed
    a lab token inside a model-persona blob like "Ace (Claude Opus, Anthropic)".
    """

    if _count_distinct_labs(s) > 1:
        return True
    if ("(" in s or ")" in s) and _PERSONA_TOKEN_RE.search(s):
        return True
    return False


def _normalize_author_name(name: str) -> str:
    return " ".join((name or "").split()).lower()


def collective_author_lab(name: str) -> Optional[str]:
    """Lab key if ``name`` is exactly an org-collective byline, else None.

    Used as a POSITIVE lab signal: an author literally named "DeepSeek-AI" or
    "GLM Team" credits its lab and is never treated as persona junk.
    """

    return ORG_COLLECTIVE_AUTHORS.get(_normalize_author_name(name))


def is_persona_author(name: str, raw_affiliation_strings: Iterable[str] = None) -> bool:
    """Whether an "author" is really an LLM persona / junk record, not a person.

    True when the display name is an org/model brand on its own ("DeepSeek"), a
    versioned model id ("Claude Sonnet 4.6"), carries two distinct model tokens
    ("Claude Sonnet"), pairs a model token with a parenthetical lab attribution
    ("Ace (Claude Opus, Anthropic)" / the mis-parsed "Anthropic) Ace (Claude"),
    or sits behind a persona / multi-lab junk affiliation blob.

    An exact org-collective byline ("DeepSeek-AI", "GLM Team") is the exception:
    it is a real lab signal, so it is NEVER a persona even though the bare brand
    name ("DeepSeek") is.
    """

    name = name or ""
    stripped = " ".join(name.split())
    if collective_author_lab(stripped):
        return False
    if stripped.lower() in _JUNK_NAME_EXACT:
        return True
    if _MODEL_VERSION_RE.search(name):
        return True
    tokens = {m.group(1).lower() for m in _PERSONA_TOKEN_RE.finditer(name)}
    if tokens and (("(" in name or ")" in name) or len(tokens) >= 2):
        return True
    for s in raw_affiliation_strings or []:
        if s and _affiliation_is_junk(s):
            return True
    return False


def match_labs_by_affiliation(
    affiliation_strings: Iterable[str],
    only: Iterable[str] = None,
) -> "Dict[str, List[str]]":
    """Match lab keys against raw affiliation strings.

    Returns a dict ``lab_key -> [evidence strings]`` so callers can show why a
    paper was attributed to a lab. Matching is case-insensitive and operates on
    affiliation strings ONLY (never the abstract or title), which keeps false
    positives low. Persona / multi-lab junk strings are skipped so a lab is only
    credited for a clean, standalone affiliation.
    """

    allowed = set(only) if only is not None else None
    strings = [s for s in affiliation_strings if s and not _affiliation_is_junk(s)]
    matched: Dict[str, List[str]] = {}
    for lab_key, patterns in _LAB_PATTERNS:
        if allowed is not None and lab_key not in allowed:
            continue
        evidence: List[str] = []
        for s in strings:
            for pat in patterns:
                if pat.search(s):
                    # Keep evidence short: it is shown verbatim in the report.
                    evidence.append(" ".join(s.split())[:EVIDENCE_MAX_LEN])
                    break
        if evidence:
            # de-duplicate while preserving order
            seen: Set[str] = set()
            uniq = [e for e in evidence if not (e in seen or seen.add(e))]
            matched[lab_key] = uniq
    return matched


def has_genai_keyword(text: str) -> bool:
    """Whether the text contains a GenAI signal (word-boundary matched).

    An unambiguous GENAI_KEYWORD anywhere is enough. The ambiguous single words
    (diffusion / transformer / generation / alignment) are NOT in that set, so
    they only qualify a paper via a specific GenAI phrase
    (AMBIGUOUS_KEYWORD_PHRASES) -- or, implicitly, when a core keyword also
    co-occurs (the core scan below returns True first). This keeps "slower
    diffusion" in an origins-of-life polymer paper from leaking in.
    """

    if not text:
        return False
    for pat in _KEYWORD_PATTERNS:
        if pat.search(text):
            return True
    for pat in _AMBIGUOUS_PHRASE_PATTERNS:
        if pat.search(text):
            return True
    return False


# Verdicts returned by classify_topic.
KEEP = "keep"
EXCLUDE = "exclude"
UNKNOWN = "unknown"

_ALWAYS_PASS_LOWER: Set[str] = {c.lower() for c in ALWAYS_PASS_CATEGORIES}


def _norm_topic(value: Optional[str]) -> str:
    return " ".join((value or "").split()).lower()


def domain_excluded(text: str) -> bool:
    """Whether the text names a non-GenAI application domain (the backstop).

    A case-insensitive substring scan for the specific application phrases in
    DOMAIN_EXCLUDE_PHRASES. Used as the cross-domain override so an ML-method
    paper applied to protein folding / traffic / steel still gets excluded even
    when its structured field looks (or is mis-classified as) computer science.
    """

    if not text:
        return False
    low = text.lower()
    return any(phrase in low for phrase in DOMAIN_EXCLUDE_PHRASES)


def has_generative_model_signal(text: str) -> bool:
    """Whether the text carries an LLM / generative-MODEL-specific signal.

    Narrower than ``has_genai_keyword``: only signals that mark a work as
    genuinely generative (language/diffusion/generative models, fine-tuning,
    multimodal, ...). The incidental boosters that leaked DP clustering work
    ("data generation", "synthetic data") are deliberately excluded.
    """

    if not text:
        return False
    return any(pat.search(text) for pat in _GENERATIVE_MODEL_SIGNAL_PATTERNS)


def privacy_clustering_excluded(text: str) -> bool:
    """Whether the text is a privacy / clustering / DP-theory topic that should
    be EXCLUDED unless a generative-model signal rescues it.

    The conditional cross-domain backstop for the differential-privacy /
    k-means / clustering-theory leak class: True only when a conditional-exclude
    phrase matches AND no generative-model signal is present.
    """

    if not text:
        return False
    if not any(pat.search(text) for pat in _CONDITIONAL_EXCLUDE_PATTERNS):
        return False
    return not has_generative_model_signal(text)


def classify_topic(paper) -> str:
    """Structured GenAI verdict for a paper: KEEP, EXCLUDE, or UNKNOWN.

    PRIMARY scope signal. EXCLUDE always wins over a later keyword hit; UNKNOWN
    means the structured signal is inconclusive and a GenAI keyword should decide
    (the historical behaviour, preserved for records with no topic/category data
    such as older OpenAlex fixtures).

    OpenAlex works classify on primary_topic field/subfield; arXiv works gate on
    their primary category. Both share the domain-phrase backstop.
    """

    primary_cat = _norm_topic(getattr(paper, "primary_category", None))
    field = _norm_topic(getattr(paper, "primary_field", None))
    subfield = _norm_topic(getattr(paper, "primary_subfield", None))
    topic = _norm_topic(getattr(paper, "primary_topic", None))

    # --- EXCLUDE gates (any one wins, ahead of every KEEP / keyword) --------
    # arXiv: a primary category outside GenAI scope (q-bio, physics.*, math.*,
    # econ.*, eess.SY, ...). Only gate when a primary category is actually known.
    if primary_cat and primary_cat not in ARXIV_GENAI_CATEGORIES:
        return EXCLUDE
    # OpenAlex: the primary topic's field / subfield is a non-GenAI domain.
    if field and field in OPENALEX_EXCLUDE_FIELDS:
        return EXCLUDE
    if subfield and subfield in OPENALEX_EXCLUDE_SUBFIELDS:
        return EXCLUDE
    # Cross-domain backstop on the human-readable text + topic name.
    text = (
        (getattr(paper, "title", "") or "") + " "
        + (getattr(paper, "abstract", "") or "") + " " + topic
    )
    if domain_excluded(text):
        return EXCLUDE
    # Conditional backstop: privacy / clustering / DP-theory work is EXCLUDED
    # unless it carries a generative-model signal (closes the DP k-means leak).
    if privacy_clustering_excluded(text):
        return EXCLUDE

    # --- KEEP gate (structured positive signal) ----------------------------
    # cs.CL is GenAI by construction (an NLP-only category) and is the only
    # structurally-decisive KEEP. We deliberately do NOT auto-keep on an OpenAlex
    # "Artificial Intelligence" subfield: OpenAlex files cryptography, quantum
    # computing, Bayesian statistics, and learning theory under that same coarse
    # subfield, so a subfield-only keep re-admits non-GenAI computer science. The
    # GenAI keyword (see topic_filter) is the positive discriminator within CS.
    if primary_cat in _ALWAYS_PASS_LOWER:
        return KEEP

    # --- otherwise inconclusive: let the keyword booster decide ------------
    # The structured signal is not decisive (any CS / unfielded record). Defer to
    # the GenAI keyword so a generative / LLM / agent / multimodal signal in the
    # text or topic name keeps it and a plain non-GenAI CS paper (crypto, theory,
    # systems, optimization) is dropped.
    return UNKNOWN


# Positive computer-science signal for an OpenAlex work, used to gate
# INSTITUTION-WIDE scans. A whole university (vs. a corporate AI lab) publishes
# across every field, so a flood of soft-science papers that merely mention an
# LLM / "generative AI" trip the keyword booster (a medical response-shift
# meta-synthesis, management-research robustness, journalism studies). Requiring
# the work's PRIMARY topic to sit in computer science (or a GenAI-adjacent CS
# subfield) keeps the watchlist-institution sections to actual CS work. People
# tracking is name-scoped to CS researchers already, so it does NOT use this.
OPENALEX_CS_FIELD = "computer science"
OPENALEX_AI_SUBFIELD_HINTS = (
    "artificial intelligence", "machine learning",
    "computer vision and pattern recognition", "computer vision",
    "natural language", "computational linguistics", "information retrieval",
    "human-computer interaction", "signal processing",
)


def work_in_cs_field(paper) -> bool:
    """Whether a work's PRIMARY OpenAlex topic is in computer science / AI.

    Strict positive gate for institution-wide scans: only the primary field /
    subfield counts (a secondary CS topic on a soft-science paper does not), so
    non-CS papers that mention GenAI in passing are dropped.
    """

    field = _norm_topic(getattr(paper, "primary_field", None))
    if field == OPENALEX_CS_FIELD:
        return True
    subfield = _norm_topic(getattr(paper, "primary_subfield", None))
    return any(h in subfield for h in OPENALEX_AI_SUBFIELD_HINTS)


def anthropic_category_in_scope(categories) -> bool:
    """Whether an Anthropic research post's subject(s) are in research scope.

    Research subjects are in-scope by default; a post is excluded only when ALL
    of its subjects are in ``ANTHROPIC_EXCLUDE_CATEGORIES`` (a pure Policy post).
    An uncategorized post is kept. ``categories`` may be a single string or a
    list of subject strings.
    """

    if isinstance(categories, str):
        categories = [categories]
    cats = [c.strip().lower() for c in (categories or []) if c and c.strip()]
    if not cats:
        return True
    return any(c not in ANTHROPIC_EXCLUDE_CATEGORIES for c in cats)
