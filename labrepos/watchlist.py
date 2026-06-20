"""Notable coding/AI engineers tracked by GitHub username.

The people analogue of labpapers' watchlist: a configurable starter set, meant
to be edited. Each entry is ``{username, note}``. Lookups are best-effort -- an
unknown or renamed username degrades gracefully (the GitHub API returns 404 and
the entry is simply skipped, never fatal).
"""

from __future__ import annotations

from typing import Dict, List

WATCHLIST_PEOPLE: List[Dict[str, str]] = [
    {"username": "karpathy", "note": "ex-OpenAI/Tesla; nanoGPT, llm.c, micrograd"},
    {"username": "ggerganov", "note": "llama.cpp, ggml, whisper.cpp"},
    {"username": "simonw", "note": "Datasette; llm CLI; prolific LLM tooling"},
    {"username": "hwchase17", "note": "LangChain founder"},
    {"username": "jerryjliu", "note": "LlamaIndex founder"},
    {"username": "philschmid", "note": "LLM fine-tuning & deployment (Hugging Face)"},
    {"username": "abetlen", "note": "llama-cpp-python"},
    {"username": "vllm-project", "note": "(org) high-throughput LLM inference"},
    {"username": "rasbt", "note": "Sebastian Raschka; LLMs-from-scratch"},
    {"username": "mckaywrigley", "note": "AI app builder; Chatbot UI"},
    {"username": "yoheinakajima", "note": "BabyAGI; autonomous agents"},
    {"username": "Significant-Gravitas", "note": "(org) AutoGPT"},
]
