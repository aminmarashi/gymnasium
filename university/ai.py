"""opencode driver — the ONLY AI path.

Everything goes through the ``opencode`` CLI (binary configurable via
``OPENCODE_BIN``). Models are listed dynamically from ``opencode models`` — no
hardcoded provider list. Generation runs ``opencode run <prompt> --model <id>
--format json`` and parses the newline-delimited JSON event stream for the
final assistant text.

The prompts deliberately ask for a clean, plain, human register — short
sentences, no marketing, no breathless "deep dive" tone (anti-NotebookLM).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Dict, List, Optional

DEFAULT_TIMEOUT = 120


def _bin() -> str:
    return os.environ.get("OPENCODE_BIN", "opencode")


class AIError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# Model listing
# --------------------------------------------------------------------------
def _provider_label(provider: str) -> str:
    pretty = provider.replace("-", " ").replace("_", " ")
    return pretty[:1].upper() + pretty[1:]


def list_models() -> Dict[str, object]:
    """Return {providers: [{provider, name, models:[{id,name}]}], error?}.

    ``opencode models`` prints one ``provider/model`` per line. We group by
    provider with no hardcoded knowledge of which providers exist.
    """
    try:
        proc = subprocess.run(
            [_bin(), "models"],
            capture_output=True, text=True, timeout=DEFAULT_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"providers": [], "error": "opencode models failed: {}".format(exc)}
    if proc.returncode != 0:
        return {"providers": [], "error": (proc.stderr or "opencode models failed").strip()}

    groups: "Dict[str, List[dict]]" = {}
    order: List[str] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line or "/" not in line:
            continue
        provider, model_id = line.split("/", 1)
        full = line
        if provider not in groups:
            groups[provider] = []
            order.append(provider)
        groups[provider].append({"id": full, "name": model_id})
    providers = [
        {"provider": p, "name": _provider_label(p), "models": groups[p]}
        for p in order
    ]
    return {"providers": providers}


# --------------------------------------------------------------------------
# Generation
# --------------------------------------------------------------------------
def _parse_stream(stdout: str) -> str:
    """Concatenate every assistant text part from the JSON event stream."""
    chunks: List[str] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            evt = json.loads(line)
        except ValueError:
            continue
        if evt.get("type") == "text":
            part = evt.get("part") or {}
            text = part.get("text")
            if text:
                chunks.append(text)
    return "".join(chunks).strip()


def generate(prompt: str, model: str, system: Optional[str] = None,
             timeout: int = DEFAULT_TIMEOUT) -> str:
    """Run one opencode completion and return the final assistant text."""
    if not model:
        raise AIError("no model specified")
    full_prompt = prompt
    if system:
        full_prompt = system.strip() + "\n\n" + prompt
    cmd = [_bin(), "run", full_prompt, "--model", model, "--format", "json"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise AIError("opencode run timed out after {}s".format(timeout))
    except OSError as exc:
        raise AIError("opencode run failed to start: {}".format(exc))
    if proc.returncode != 0:
        raise AIError((proc.stderr or "opencode run failed").strip()[:500])
    text = _parse_stream(proc.stdout)
    if not text:
        # Some builds emit plain text rather than the event stream.
        text = (proc.stdout or "").strip()
    if not text:
        raise AIError("opencode returned no text")
    return text


# --------------------------------------------------------------------------
# JSON extraction helper
# --------------------------------------------------------------------------
def _extract_json(text: str) -> Optional[object]:
    """Pull the first JSON object/array out of a model reply."""
    text = text.strip()
    # Strip ```json fences if present.
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    # Find the first balanced {...} or [...].
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        if start == -1:
            continue
        depth = 0
        for i in range(start, len(text)):
            if text[i] == opener:
                depth += 1
            elif text[i] == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except ValueError:
                        break
    try:
        return json.loads(text)
    except ValueError:
        return None


_PLAIN_REGISTER = (
    "You write for a curious student. Use plain, calm language and short "
    "sentences. No hype, no marketing tone, no filler like 'dive in' or "
    "'fascinating'. Be concrete and honest."
)


# --------------------------------------------------------------------------
# Higher-level tasks
# --------------------------------------------------------------------------
def summarize_item(item: dict, model: str) -> Dict[str, object]:
    """Return {summary: [bullet, ...], terms: [term, ...]} in one call."""
    title = item.get("title", "")
    abstract = item.get("abstract") or item.get("why") or ""
    prompt = (
        "Summarize this {kind} for a reader meeting it for the first time.\n\n"
        "Title: {title}\n\nText:\n{abstract}\n\n"
        "Return ONLY JSON of the form "
        '{{"summary": ["bullet", "bullet", "bullet"], "terms": ["term", "term"]}}. '
        "Give 2 to 4 short bullet lines (one plain sentence each) and a list of "
        "the key technical terms a learner should know."
    ).format(kind=item.get("kind", "item"), title=title, abstract=abstract[:4000])
    text = generate(prompt, model, system=_PLAIN_REGISTER)
    data = _extract_json(text) or {}
    summary = data.get("summary") if isinstance(data, dict) else None
    terms = data.get("terms") if isinstance(data, dict) else None
    if not isinstance(summary, list) or not summary:
        summary = [s.strip() for s in re.split(r"\n+", text) if s.strip()][:4] or [text[:200]]
    if not isinstance(terms, list):
        terms = []
    return {
        "summary": [str(s) for s in summary][:4],
        "terms": [str(t) for t in terms][:12],
    }


def _grounding_block(kb_notes: Optional[List[dict]] = None,
                     graph: Optional[dict] = None) -> str:
    """Render the user's own KB notes + concept map as a compact context block.

    Wrapped in BEGIN_GROUNDING/END_GROUNDING sentinels so it is easy to spot in
    the prompt (and verifiable in tests). Returns "" when there is nothing.
    """
    lines: List[str] = []
    for n in (kb_notes or []):
        term = (n.get("term") or "").strip()
        definition = (n.get("definition") or "").strip()
        if term or definition:
            lines.append("- {}: {}".format(term, definition) if definition else "- {}".format(term))
    concepts = list((graph or {}).get("concepts") or [])
    edges = list((graph or {}).get("edges") or [])
    if concepts:
        lines.append("Concepts you have mapped: " + ", ".join(str(c) for c in concepts))
    if edges:
        lines.append("Links between them: " + "; ".join(str(e) for e in edges))
    if not lines:
        return ""
    return "BEGIN_GROUNDING\n" + "\n".join(lines) + "\nEND_GROUNDING"


def explain(span_text: str, mode: str, item: dict, model: str,
            history: Optional[List[dict]] = None,
            kb_notes: Optional[List[dict]] = None,
            graph: Optional[dict] = None) -> Dict[str, object]:
    """Explain/summarize/answer about a selected span.

    Returns {lead, body, analogy?}. ``mode`` is explain | summarize | ask.
    ``history`` is a list of {role, content} prior turns (used for 'ask').
    ``kb_notes``/``graph`` optionally ground the answer in the reader's own
    saved knowledge base and concept map (used for follow-up questions).
    """
    title = item.get("title", "") if item else ""
    context = item.get("abstract") or item.get("why") or "" if item else ""
    if mode == "summarize":
        instr = (
            "Summarize the selected passage in plain words. "
            "Return JSON {\"lead\": short headline, \"body\": one short paragraph}. "
            "Do not include an analogy."
        )
    elif mode == "ask":
        instr = (
            "Answer the reader's question about the selected text. "
            "Return JSON {\"lead\": short headline, \"body\": one short paragraph, "
            "\"analogy\": one everyday comparison}."
        )
    else:  # explain
        instr = (
            "Explain the selected text simply, as if to a bright newcomer. "
            "Return JSON {\"lead\": short headline, \"body\": one short paragraph, "
            "\"analogy\": one everyday comparison}."
        )
    hist_block = ""
    if history:
        turns = []
        for h in history:
            who = "Reader" if h.get("role") == "user" else "You"
            turns.append("{}: {}".format(who, h.get("content", "")))
        hist_block = "\n\nConversation so far:\n" + "\n".join(turns)
    ground = _grounding_block(kb_notes, graph)
    ground_block = ""
    if ground:
        ground_block = (
            "\n\nDraw on the reader's own saved notes and concept map below when "
            "relevant:\n" + ground)
    prompt = (
        "Source: {title}\nContext: {context}\n\n"
        "Selected text: \"{span}\"{ground}{hist}\n\n{instr}\n"
        "Return ONLY the JSON object."
    ).format(title=title, context=context[:1500], span=span_text[:1500],
             ground=ground_block, hist=hist_block, instr=instr)
    text = generate(prompt, model, system=_PLAIN_REGISTER)
    data = _extract_json(text)
    if isinstance(data, dict) and (data.get("lead") or data.get("body")):
        out = {
            "lead": str(data.get("lead") or "").strip(),
            "body": str(data.get("body") or "").strip(),
        }
        if mode != "summarize" and data.get("analogy"):
            out["analogy"] = str(data["analogy"]).strip()
        return out
    # Fallback: treat the whole reply as the body.
    return {"lead": "In plain words", "body": text.strip()}


def chat(item: dict, history: Optional[List[dict]], message: str,
         kb_notes: Optional[List[dict]] = None, graph: Optional[dict] = None,
         excerpt: Optional[str] = None, model: str = "") -> Dict[str, object]:
    """Answer a question ABOUT the whole article, grounded in the user's KB.

    Returns {lead, body}. The answer is grounded in the supplied knowledge-base
    notes and concept map, explicitly drawing on what the reader already saved
    or mapped when it is relevant. Reuses the opencode ``generate`` path.
    """
    title = item.get("title", "") if item else ""
    if excerpt is None:
        excerpt = (item.get("summary_readable") if item else None) or \
            (item.get("abstract") or item.get("why") or "" if item else "")
        if isinstance(excerpt, list):
            excerpt = " ".join(str(s) for s in excerpt)
    hist_block = ""
    if history:
        turns = []
        for h in history:
            who = "Reader" if h.get("role") == "user" else "You"
            turns.append("{}: {}".format(who, h.get("content", "")))
        hist_block = "\n\nConversation so far:\n" + "\n".join(turns)
    ground = _grounding_block(kb_notes, graph)
    ground_block = ""
    if ground:
        ground_block = (
            "\n\nGround your answer in the reader's OWN saved notes and concept "
            "map below. When something here is relevant, use it and refer to what "
            "they already saved or mapped:\n" + ground)
    prompt = (
        "ARTICLE_CHAT_MODE. You are chatting with a reader about a whole "
        "article.\n\nArticle title: {title}\nArticle excerpt:\n{excerpt}"
        "{ground}{hist}\n\nReader's question: \"{message}\"\n\n"
        "Answer the question about the article in plain words. "
        "Return ONLY JSON {{\"lead\": short headline, \"body\": one short "
        "paragraph}}."
    ).format(title=title, excerpt=str(excerpt)[:1500], ground=ground_block,
             hist=hist_block, message=(message or "")[:1500])
    text = generate(prompt, model, system=_PLAIN_REGISTER)
    data = _extract_json(text)
    if isinstance(data, dict) and (data.get("lead") or data.get("body")):
        return {
            "lead": str(data.get("lead") or "").strip(),
            "body": str(data.get("body") or "").strip(),
        }
    return {"lead": "In plain words", "body": text.strip()}


def extract_concepts(span_text: str, item: Optional[dict], model: str) -> Dict[str, object]:
    """Name the salient concept(s) in a selected span for the glossary.

    Returns ``{"concepts": [label, ...], "question": str | None}``. The model is
    asked for 1 to 3 normalized terms a learner would look up. When the
    selection is too vague to name a clear concept it returns a single short
    clarifying question instead (with ``concepts`` empty) so the caller can ask
    the reader rather than guessing. Reuses the opencode ``generate`` path and
    keeps the same calm, plain register as the other tasks.
    """
    title = item.get("title", "") if item else ""
    context = (item.get("abstract") or item.get("why") or "") if item else ""
    prompt = (
        "Source: {title}\nContext: {context}\n\n"
        "Selected text: \"{span}\"\n\n"
        "Name the salient concept(s) or keyword(s) in the selected text as a "
        "short list of 1 to 3 normalized terms — each a noun phrase a learner "
        "would look up in a glossary (not a whole sentence). If the selection "
        "is too vague to name a clear concept, do NOT guess: instead ask ONE "
        "short clarifying question.\n"
        "Return ONLY JSON. When clear: {{\"concepts\": [\"term\", ...], "
        "\"question\": null}}. When unclear: {{\"concepts\": [], \"question\": "
        "\"your question\"}}."
    ).format(title=title, context=str(context)[:1500], span=str(span_text)[:1500])
    text = generate(prompt, model, system=_PLAIN_REGISTER)
    data = _extract_json(text)
    concepts: List[str] = []
    question: Optional[str] = None
    if isinstance(data, dict):
        raw = data.get("concepts")
        if isinstance(raw, list):
            for c in raw:
                label = str(c).strip()
                if label and label not in concepts:
                    concepts.append(label)
        q = data.get("question")
        if q is not None and str(q).strip():
            question = str(q).strip()
    concepts = concepts[:3]
    # Only surface the clarifying question when there is no clear concept.
    if concepts:
        question = None
    elif not question:
        # Defensive fallback: treat the trimmed span itself as the concept so
        # the flow never dead-ends on a malformed reply.
        fallback = re.sub(r"\s+", " ", str(span_text or "")).strip()
        if fallback:
            concepts = [fallback[:60]]
    return {"concepts": concepts, "question": question}


def suggest_links(concept: dict, others: List[dict], model: str) -> List[int]:
    """Return ids (from ``others``) the concept is most related to."""
    if not others:
        return []
    listing = "\n".join("- id {}: {}".format(o["id"], o["label"]) for o in others)
    prompt = (
        "Concept: \"{label}\".\n\nOther concepts:\n{listing}\n\n"
        "Which other concepts are directly related to \"{label}\" "
        "(one explains or builds on the other)? "
        "Return ONLY a JSON array of the matching id numbers, e.g. [3, 7]. "
        "Return [] if none are clearly related."
    ).format(label=concept["label"], listing=listing)
    text = generate(prompt, model, system=_PLAIN_REGISTER)
    data = _extract_json(text)
    valid = {o["id"] for o in others}
    out: List[int] = []
    if isinstance(data, list):
        for v in data:
            try:
                iv = int(v)
            except (ValueError, TypeError):
                continue
            if iv in valid and iv not in out:
                out.append(iv)
    return out
