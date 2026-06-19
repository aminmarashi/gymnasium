"""Netherlands GenAI map / watchlist (increment 3) -- static configuration.

Tracks named PEOPLE and NL research INSTITUTIONS independent of the six big
labs, plus a curated companies reference appendix. All paper tracking honours
the same STRICT GenAI structured topic filter and quality gates as the lab
pipeline; the companies list is reference-only (never paper-tracked).

Nothing here hits the network: institutions are resolved to OpenAlex ids at
runtime (and cached) from the search terms below, and people are resolved by
name. Per-entry resolution failures degrade gracefully -- an unresolved person
or institution is flagged, never fatal.
"""

from __future__ import annotations

from typing import Dict, List

# ---------------------------------------------------------------------------
# People -- NL-based researchers (ordered; rendered in this order).
# Each entry: {name, note, verify}. ``verify=True`` flags names whose current
# affiliation we want a human to double-check in the report.
# ---------------------------------------------------------------------------
WATCHLIST_PEOPLE: List[Dict] = [
    {"name": "Max Welling",
     "note": "AMLab/UvA; CuspAI CTO; geometric & equivariant deep learning",
     "verify": False},
    {"name": "Tim Salimans",
     "note": "diffusion & distillation (ex-Google DeepMind)",
     "verify": True},
    {"name": "Emiel Hoogeboom",
     "note": "diffusion models; equivariant generative models",
     "verify": True},
    {"name": "David Ruhe",
     "note": "geometric / Clifford neural networks",
     "verify": False},
    {"name": "Jonathan Heek",
     "note": "JAX & diffusion; Google DeepMind Amsterdam",
     "verify": False},
    {"name": "Thomas Mensink",
     "note": "vision-language; Google Research",
     "verify": False},
    {"name": "Taco Cohen",
     "note": "equivariant deep learning; Qualcomm AI Research",
     "verify": False},
    {"name": "Ivan Titov",
     "note": "NLP; UvA / Edinburgh",
     "verify": False},
    {"name": "Wilker Aziz",
     "note": "NLP & probabilistic models; UvA",
     "verify": False},
    {"name": "Christof Monz",
     "note": "machine translation; UvA",
     "verify": False},
    {"name": "Raquel Fernandez",
     "note": "dialogue & NLP; UvA ILLC",
     "verify": False},
    {"name": "Jelle Zuidema",
     "note": "NLP interpretability; UvA",
     "verify": False},
    {"name": "Ekaterina Shutova",
     "note": "NLP; UvA",
     "verify": False},
    {"name": "Cees Snoek",
     "note": "computer vision; UvA",
     "verify": False},
    {"name": "Amirhossein Habibian",
     "note": "efficient generative video; Qualcomm AI Research",
     "verify": False},
    {"name": "Bob van Luijt",
     "note": "Weaviate founder; vector DB / RAG infra",
     "verify": False},
    {"name": "Joris Castermans",
     "note": "Whispp founder; real-time voice reconstruction",
     "verify": False},
    {"name": "Akash Raj Komarlu",
     "note": "Whispp; on-device voice AI",
     "verify": False},
    {"name": "Jan-Willem van de Meent",
     "note": "probabilistic programming; UvA AMLab",
     "verify": False},
    {"name": "Erik Bekkers",
     "note": "geometric deep learning; UvA",
     "verify": False},
    {"name": "Victor Garcia Satorras",
     "note": "equivariant graph neural networks (ex-UvA)",
     "verify": False},
    {"name": "Clement Vignac",
     "note": "diffusion for graphs & molecules",
     "verify": False},
]

# Dutch-origin researchers who are NOT NL-based: rendered in a distinct
# sub-bucket and never counted as NL.
WATCHLIST_PEOPLE_ABROAD: List[Dict] = [
    {"name": "Diederik P. Kingma",
     "note": "VAE / Adam; now Anthropic; Dutch-origin, not NL-based",
     "verify": False,
     "abroad": True},
]

# ---------------------------------------------------------------------------
# Institutions -- NL research nodes. Each entry: {label, search_term, ...}.
# Resolution is constrained to NL-specific OpenAlex institutions (country_code
# NL) so a node never resolves to a global/foreign org of the same name --
# "Qualcomm" must not become Qualcomm (United States), "Microsoft Research" must
# not become Microsoft Research (United Kingdom). A node with no distinct NL
# OpenAlex institution is marked ``people_tracked`` and its institution-wide
# paper pull is SKIPPED (its output is already covered via the people list), so
# worldwide papers are never pulled under an NL label. Optionally pin a vetted
# ``openalex_id`` when a clean NL id is known. Google DeepMind Amsterdam is
# already covered by the Google lab, so it is deliberately NOT duplicated here.
WATCHLIST_INSTITUTIONS: List[Dict] = [
    {"label": "University of Amsterdam",
     "search_term": "University of Amsterdam"},  # AMLab/ILLC/ELLIS (NL)
    # DELIBERATE: these two have no distinct NL OpenAlex institution; an
    # institution scan would pull the global org (Qualcomm US / MS Research UK)
    # -- the prior HIGH bug -- so they are people_tracked on purpose, covered via
    # the people watchlist below. Do NOT revert to institution scans / global ids.
    {"label": "Qualcomm AI Research / QUVA",
     "search_term": "Qualcomm",
     "people_tracked": True,
     "note": ("no distinct NL OpenAlex institution; covered via Taco Cohen / "
              "Amirhossein Habibian in the people list")},
    {"label": "Microsoft Research AI4Science Amsterdam",
     "search_term": "Microsoft Research",
     "people_tracked": True,
     "note": ("no distinct NL OpenAlex institution; AI4Science Amsterdam "
              "covered via Max Welling in the people list")},
]

# ---------------------------------------------------------------------------
# Companies -- curated reference appendix. NOT paper-tracked.
# ---------------------------------------------------------------------------
REFERENCE_COMPANIES: List[Dict] = [
    {"name": "Cradle",
     "location": "Amsterdam / Zurich",
     "note": ("generative protein engineering; $73M Series B (2024); ML team "
              "in Zurich, wet lab in Amsterdam")},
    {"name": "CuspAI",
     "location": "Cambridge HQ + Amsterdam Science Park (2nd-largest site)",
     "note": ("generative AI for materials; CTO Max Welling; raising ~$400M "
              "@ ~$2.6B; customers incl. ASML, Meta, Hyundai")},
    {"name": "Weaviate",
     "location": "Amsterdam",
     "note": "open-source vector DB / RAG infra; founder Bob van Luijt"},
    {"name": "Orq.ai",
     "location": "Amsterdam",
     "note": "LLMOps / evals / agent lifecycle / gateway; OrqKit"},
    {"name": "Whispp",
     "location": "Leiden",
     "note": ("real-time on-device voice reconstruction; EUR2.5M EIC (2026); "
              "Castermans, Komarlu")},
    {"name": "Hadrian",
     "location": "Amsterdam",
     "note": ("agentic AI for offensive security; LLM ReAct pentesting; "
              "dual-use")},
]

# What deliberately does NOT belong on the companies list.
EXCLUSIONS_NOTE: str = (
    "Excluded: generic AI consultancies / chatbot agencies / "
    "content-automation shops / prompt-orchestration-only tools; and "
    "Amsterdam-HQ-but-not-Dutch-technical-center companies (e.g. Wonderful, "
    "whose R&D is in Israel)."
)
