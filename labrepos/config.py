"""Static configuration: giants (orgs), topic keywords, and run defaults.

Two organizing pieces, paralleling labpapers' config:

1. GIANTS -- an ordered registry of selectable "giants". A giant is a lab or a
   coding / dev-AI-tooling org, each owning one or more GitHub org logins. Every
   org login here was GROUNDED against the live GitHub API (all resolve 200);
   there are no phantom orgs.

2. A STRICT GenAI / agentic-coding topic model. Broad orgs (microsoft, github,
   facebookresearch, jetbrains) carry far more non-GenAI work than GenAI, so the
   filter must be strict. It mirrors labpapers' hard-won keyword-leak fixes:
   unambiguous keeps in GENAI_KEYWORDS, bare ambiguous terms (agent, diffusion,
   transformer, ...) that keep ONLY inside a qualifying phrase, a structured
   EXCLUDE backstop, and GitHub-topic-driven structured KEEP.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Pattern, Set


# ---------------------------------------------------------------------------
# Giants
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class GiantConfig:
    """A selectable giant: a lab or coding/dev-AI org owning GitHub org logins."""

    key: str
    display_name: str
    family: str  # "lab" | "coding"
    orgs: List[str] = field(default_factory=list)


GIANTS: "OrderedDict[str, GiantConfig]" = OrderedDict()


def _add(g: GiantConfig) -> None:
    GIANTS[g.key] = g


# --- Labs ------------------------------------------------------------------
_add(GiantConfig("anthropic", "Anthropic", "lab", ["anthropics"]))
_add(GiantConfig("meta", "Meta", "lab", ["facebookresearch", "meta-llama"]))
_add(GiantConfig(
    "google", "Google (incl. DeepMind)", "lab",
    ["google-research", "google-deepmind", "google-gemini"],
))
_add(GiantConfig("openai", "OpenAI", "lab", ["openai"]))
_add(GiantConfig("zai", "Z.AI (Zhipu)", "lab", ["zai-org", "THUDM"]))
_add(GiantConfig("deepseek", "DeepSeek", "lab", ["deepseek-ai"]))

# --- Coding / dev-AI tooling -----------------------------------------------
_add(GiantConfig("microsoft", "Microsoft", "coding", ["microsoft"]))
# github is its OWN giant (not folded under microsoft) so it is independently
# selectable.
_add(GiantConfig("github", "GitHub", "coding", ["github"]))
_add(GiantConfig("cursor", "Cursor (Anysphere)", "coding", ["anysphere"]))
_add(GiantConfig("cline", "Cline", "coding", ["cline"]))
# sst -> anomalyco is a confirmed org relocation (OpenCode).
_add(GiantConfig("opencode", "OpenCode", "coding", ["anomalyco"]))
_add(GiantConfig("openhands", "OpenHands (All-Hands-AI)", "coding", ["All-Hands-AI"]))
# block -> aaif-goose is a confirmed org relocation (Goose).
_add(GiantConfig("goose", "Goose", "coding", ["aaif-goose"]))
_add(GiantConfig("aider", "Aider", "coding", ["Aider-AI"]))
_add(GiantConfig("continue", "Continue", "coding", ["continuedev"]))
_add(GiantConfig("sourcegraph", "Sourcegraph", "coding", ["sourcegraph"]))
_add(GiantConfig("roocode", "Roo Code", "coding", ["RooCodeInc"]))
_add(GiantConfig("langchain", "LangChain", "coding", ["langchain-ai"]))
_add(GiantConfig("llamaindex", "LlamaIndex", "coding", ["run-llama"]))
_add(GiantConfig("crewai", "CrewAI", "coding", ["crewAIInc"]))
_add(GiantConfig("huggingface", "Hugging Face", "coding", ["huggingface"]))
_add(GiantConfig("vercel", "Vercel", "coding", ["vercel"]))
_add(GiantConfig("mistral", "Mistral AI", "coding", ["mistralai"]))
_add(GiantConfig("replit", "Replit", "coding", ["replit"]))
_add(GiantConfig("jetbrains", "JetBrains", "coding", ["JetBrains"]))

# Synthetic giant bucket for watchlist-person-sourced repos (people analogue of
# labpapers' watchlist). Not part of GIANTS (not org-selectable), but a stable
# key the people sources tag and the report groups last.
PEOPLE_GIANT_KEY = "people"
PEOPLE_GIANT_DISPLAY = "Watchlist people"


def selected_giants(keys: Iterable[str]) -> "OrderedDict[str, GiantConfig]":
    """Subset of GIANTS for the given keys, preserving GIANTS order."""

    wanted = {k.strip().lower() for k in keys if k and k.strip()}
    return OrderedDict((k, v) for k, v in GIANTS.items() if k.lower() in wanted)


def _org_to_giant() -> Dict[str, str]:
    lookup: Dict[str, str] = {}
    for g in GIANTS.values():
        for org in g.orgs:
            lookup[org.lower()] = g.key
    return lookup


ORG_TO_GIANT: Dict[str, str] = _org_to_giant()


def giant_for_org(org: str) -> Optional[str]:
    return ORG_TO_GIANT.get((org or "").lower())


def giants_for_family(family: str) -> List[str]:
    return [k for k, g in GIANTS.items() if g.family == family]


def giant_display_name(key: str) -> str:
    if key == PEOPLE_GIANT_KEY:
        return PEOPLE_GIANT_DISPLAY
    g = GIANTS.get(key)
    return g.display_name if g else key


# ---------------------------------------------------------------------------
# Topic model -- STRICT GenAI / agentic-coding scope.
# ---------------------------------------------------------------------------
# Unambiguous keeps: a single hit anywhere in name + description + topics +
# language is enough. Mirrors labpapers' GENAI_KEYWORDS discipline -- bare
# ambiguous terms (agent, reasoning, diffusion, transformer, inference, prompt,
# model) are deliberately NOT here; they keep only via AMBIGUOUS_KEYWORD_PHRASES.
GENAI_KEYWORDS: List[str] = [
    "llm",
    "llms",
    "large language model",
    "language model",
    "agentic",
    "foundation model",
    "tool use",
    "tool-use",
    "mcp",
    "model context protocol",
    "rag",
    "retrieval-augmented",
    "retrieval augmented",
    "multimodal",
    "vlm",
    "text-to-image",
    "text-to-video",
    "fine-tune",
    "fine-tuning",
    "fine tuning",
    "finetuning",
    "llm inference",
    "prompt engineering",
    "coding agent",
    "code generation",
    "copilot",
    "chatbot",
    "gpt",
    "claude",
    "gemini",
    "llama",
    "qwen",
    "mixture-of-experts",
    "mixture of experts",
    "embeddings",
    "generative ai",
    "genai",
    "rlhf",
    "in-context learning",
    "chain-of-thought",
    "chain of thought",
    "diffusion model",
]

# Bare ambiguous terms keep ONLY inside one of these qualifying phrases, so
# graphics / EE / optics / web repos in microsoft / facebookresearch / google do
# not leak in on a lone "agent" / "diffusion" / "transformer" / "inference".
AMBIGUOUS_KEYWORD_PHRASES: List[str] = [
    # agent: AI agents, not HTTP user-agents or RL game agents
    "ai agent",
    "llm agent",
    "autonomous agent",
    "agent framework",
    "multi-agent",
    "agent workflow",
    # diffusion: generative diffusion models, not physical/heat diffusion
    "diffusion model",
    "stable diffusion",
    "latent diffusion",
    "diffusion-based",
    "denoising diffusion",
    # transformer: the architecture, not electrical transformers
    "transformer model",
    "transformer language model",
    "transformer architecture",
    "vision transformer",
    "pretrained transformer",
    # inference: LLM/model inference serving, not statistical inference
    "llm inference",
    "model inference",
    "inference engine",
    "inference server",
    # reasoning: model reasoning, not generic logic
    "reasoning model",
    "llm reasoning",
    # prompt: prompt engineering / prompting, not CLI prompts
    "prompt engineering",
    "system prompt",
    "prompt template",
]

# Structured KEEP: GitHub topic slugs that are decisively GenAI/agentic. A repo
# that carries any of these as a GitHub topic is kept regardless of the keyword
# booster (the structured positive signal, analogous to labpapers' cs.CL keep).
GENAI_TOPICS: Set[str] = {
    "llm", "llms", "large-language-models", "large-language-model",
    "language-model", "language-models", "generative-ai", "genai", "gen-ai",
    "agent", "agents", "ai-agent", "ai-agents", "agentic", "agentic-ai",
    "autonomous-agents", "llm-agent", "multi-agent",
    "rag", "retrieval-augmented-generation",
    "chatbot", "chatbots", "gpt", "gpt-4", "chatgpt", "openai", "anthropic",
    "claude", "gemini", "llama", "qwen", "mistral",
    "prompt-engineering", "prompt", "prompting",
    "fine-tuning", "finetuning", "instruction-tuning", "rlhf",
    "multimodal", "vlm", "vision-language", "text-to-image", "text-to-video",
    "diffusion", "diffusion-models", "stable-diffusion",
    "mcp", "model-context-protocol",
    "embeddings", "vector-database", "vector-search",
    "transformers", "transformer", "foundation-models", "foundation-model",
    "mixture-of-experts", "moe", "inference", "llm-inference", "llmops",
    "coding-agent", "ai-coding", "code-generation", "copilot",
}
# NOTE: broad, non-GenAI-specific GitHub topics (machine-learning, deep-learning,
# ml, ai, data-science, neural-network, nlp) are deliberately NOT structural
# keeps -- a classic-ML/infra repo from a broad org (e.g. microsoft) must not
# pass on those generic tags alone. A repo is kept structurally only on a
# GenAI/agentic-SPECIFIC topic above; otherwise it must earn KEEP via a
# qualifying GenAI keyword (see has_genai_keyword / topic_filter).

# Structured EXCLUDE: GitHub topic slugs that clearly mark a non-GenAI repo.
# A match here wins over any KEEP / keyword (EXCLUDE always wins).
EXCLUDE_TOPICS: Set[str] = {
    "dotfiles", "homebrew", "homebrew-tap", "homebrew-cask",
    "blog", "website", "personal-website", "portfolio", "jekyll", "hugo",
    "awesome", "awesome-list",
    "documentation", "docs",
    "game", "gamedev", "game-engine", "game-development",
    "ui-kit", "design-system", "icons", "icon", "wallpaper", "wallpapers",
    "theme", "themes", "color-scheme",
    "hardware", "driver", "drivers", "kernel", "firmware", "bios",
    "font", "fonts",
}

# Structured EXCLUDE backstop over name + description text. Specific phrases that
# betray a non-GenAI repo even when no excluding topic is set. Kept deliberately
# narrow so it never fires on a genuine GenAI repo.
EXCLUDE_KEYWORDS: List[str] = [
    "dotfiles",
    "homebrew tap", "homebrew-tap", "brew tap",
    "personal website", "personal blog", "my blog", "my website",
    "awesome list", "curated list of",
    "documentation site", "docs site",
    "wallpaper", "icon pack", "icon set", "color scheme", "colorscheme",
    "game engine", "device driver", "kernel module",
    "static site generator",
]


def _compile_keyword_patterns(keywords: List[str]) -> List[Pattern[str]]:
    return [
        re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)
        for kw in keywords
    ]


_KEYWORD_PATTERNS: List[Pattern[str]] = _compile_keyword_patterns(GENAI_KEYWORDS)
_AMBIGUOUS_PHRASE_PATTERNS: List[Pattern[str]] = _compile_keyword_patterns(
    AMBIGUOUS_KEYWORD_PHRASES
)
_EXCLUDE_KEYWORD_PATTERNS: List[Pattern[str]] = _compile_keyword_patterns(
    EXCLUDE_KEYWORDS
)


# Verdicts returned by classify_topic.
KEEP = "keep"
EXCLUDE = "exclude"
UNKNOWN = "unknown"  # inconclusive -> let the keyword booster decide

# Run defaults.
DEFAULT_DAYS = 30
NOTABLE_STARS = 500


def _norm_topic(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def has_genai_keyword(text: str) -> bool:
    """Whether the text carries a GenAI signal (word-boundary matched).

    An unambiguous GENAI_KEYWORD anywhere is enough. The bare ambiguous terms
    (agent / diffusion / transformer / inference / reasoning / prompt) only
    qualify a repo via a specific AMBIGUOUS_KEYWORD_PHRASE -- so a graphics
    "heat diffusion" or an electrical "power transformer" repo does NOT keep.
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


def _repo_text(repo) -> str:
    parts = [
        getattr(repo, "name", "") or "",
        getattr(repo, "description", "") or "",
        " ".join(getattr(repo, "topics", []) or []),
        getattr(repo, "language", "") or "",
    ]
    return " ".join(parts)


def classify_topic(repo) -> str:
    """Structured GenAI verdict for a repo: KEEP, EXCLUDE, or UNKNOWN.

    EXCLUDE always wins (an excluding GitHub topic or an EXCLUDE_KEYWORD in the
    name/description). A decisively-GenAI GitHub topic is a structural KEEP.
    Otherwise the verdict is UNKNOWN and the keyword booster decides (see
    sources.base.topic_filter).
    """

    topics = {_norm_topic(t) for t in (getattr(repo, "topics", []) or [])}

    # --- EXCLUDE gates (win ahead of every KEEP / keyword) ------------------
    if topics & EXCLUDE_TOPICS:
        return EXCLUDE
    name_desc = "{n} {d}".format(
        n=getattr(repo, "name", "") or "",
        d=getattr(repo, "description", "") or "",
    )
    for pat in _EXCLUDE_KEYWORD_PATTERNS:
        if pat.search(name_desc):
            return EXCLUDE

    # --- KEEP gate (structured positive GitHub topic) -----------------------
    if topics & GENAI_TOPICS:
        return KEEP

    # --- otherwise inconclusive: keyword booster decides --------------------
    return UNKNOWN
