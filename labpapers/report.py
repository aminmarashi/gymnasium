"""Render the run result as Markdown and JSON.

Markdown leads with the Key People ranking (the organizing principle made
visible), then per-lab paper sections sorted by impact signal.
"""

from __future__ import annotations

import json
import os
from typing import List, Optional

from . import config
from .model import Author, Paper
from .pipeline import Result, papers_for_lab

MAX_AUTHORS_SHOWN = 8


def _giant_mark(flag: bool) -> str:
    return " \U0001F31F" if flag else ""  # star


def _lab_name(key: str) -> str:
    lab = config.LABS.get(key)
    return lab.display_name if lab else key


def _author_line(authors: List, limit: int = MAX_AUTHORS_SHOWN) -> str:
    names: List[str] = []
    for a in authors[:limit]:
        names.append(a.name + (_giant_mark(getattr(a, "is_giant", False))))
    extra = len(authors) - limit
    line = ", ".join(n for n in names if n.strip())
    if extra > 0:
        line += ", +{n} more".format(n=extra)
    return line or "(authors unavailable)"


def _person_row(rank: int, a: Author, show_lab: bool = True) -> str:
    parts = [
        "{rank}. **{name}**{giant}".format(
            rank=rank, name=a.name or "(unknown)", giant=_giant_mark(a.is_giant)
        ),
    ]
    meta = []
    if show_lab and a.lab:
        meta.append(_lab_name(a.lab))
    meta.append("citations {c:,}".format(c=a.cited_by_count))
    meta.append("h-index {h}".format(h=a.h_index))
    meta.append("works {w:,}".format(w=a.works_count))
    if a.last_institution_name:
        meta.append(a.last_institution_name)
    return parts[0] + " — " + ", ".join(meta)


def render_markdown(result: Result, generated_at: Optional[str] = None) -> str:
    lines: List[str] = []
    lines.append("# GenAI lab-paper tracker")
    lines.append("")
    window = "{frm} → {to}".format(frm=result.from_date, to=result.to_date)
    lines.append("- **Window:** {window}".format(window=window))
    lines.append(
        "- **Labs:** {labs}".format(
            labs=", ".join(_lab_name(k) for k in result.labs)
        )
    )
    if generated_at:
        lines.append("- **Generated:** {ts}".format(ts=generated_at))
    lines.append("- **Total papers:** {n}".format(n=len(result.papers)))
    counts = ", ".join(
        "{lab}: {n}".format(lab=_lab_name(k), n=result.per_lab_counts.get(k, 0))
        for k in result.labs
    )
    lines.append("- **Per-lab counts:** {counts}".format(counts=counts))
    lines.append("")
    lines.append(
        "> Sorted by **author prominence** (giant-weight): a paper's signal is "
        "driven by its authors' citation impact, so work by/with giants rises "
        "to the top. \U0001F31F marks a giant "
        "(citations ≥ {c:,} or h-index ≥ {h}).".format(
            c=result.giant_cited_by, h=result.giant_hindex
        )
    )
    lines.append("")

    # --- Key People (FIRST) -------------------------------------------------
    lines.append("## Key People")
    lines.append("")
    if result.people_overall:
        lines.append("### Overall")
        lines.append("")
        for i, a in enumerate(result.people_overall, 1):
            lines.append(_person_row(i, a, show_lab=True))
        lines.append("")
    else:
        lines.append("_No people ranked._")
        lines.append("")

    for key in result.labs:
        people = result.people_by_lab.get(key) or []
        if not people:
            continue
        lines.append("### {lab}".format(lab=_lab_name(key)))
        lines.append("")
        for i, a in enumerate(people, 1):
            lines.append(_person_row(i, a, show_lab=False))
        lines.append("")

    # --- Netherlands GenAI map (watchlist) ----------------------------------
    if result.watchlist is not None:
        lines.extend(_render_watchlist(result.watchlist))

    # --- Papers by lab ------------------------------------------------------
    lines.append("## Papers by lab")
    lines.append("")
    for key in result.labs:
        lab_papers = papers_for_lab(result.papers, key)
        lines.append("### {lab} ({n})".format(lab=_lab_name(key), n=len(lab_papers)))
        lines.append("")
        if not lab_papers:
            lines.append("_No matched papers in window._")
            lines.append("")
            continue
        for paper in lab_papers:
            lines.extend(_render_paper(paper))
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _paper_link(paper: Paper) -> Optional[str]:
    return paper.abs_url or _doi_link(paper) or paper.source_url


def _watchlist_paper_line(paper: Paper) -> str:
    """One compact bullet for a watchlist paper: title (linked), date, signal."""

    title = paper.title or "(untitled)"
    link = _paper_link(paper)
    head = "[{t}]({u})".format(t=title, u=link) if link else title
    meta = []
    if paper.date:
        meta.append("date {d}".format(d=paper.date))
    meta.append("signal: {s}".format(s=paper.impact_summary()))
    if paper.has_giant_author:
        meta.append("giant-author \U0001F31F")
    return "  - {head} — {meta}".format(head=head, meta=" | ".join(meta))


def _render_watchlist(wl) -> List[str]:
    out: List[str] = []
    out.append("## Netherlands GenAI map (watchlist)")
    out.append("")

    out.append("### People")
    out.append("")
    if not wl.people:
        out.append("_No people tracked._")
        out.append("")
    for person in wl.people:
        out.extend(_render_watchlist_person(person))

    if wl.people_abroad:
        out.append("#### Dutch-origin, abroad")
        out.append("")
        for person in wl.people_abroad:
            out.extend(_render_watchlist_person(person))

    out.append("### Research institutions")
    out.append("")
    if not wl.institutions:
        out.append("_No institutions tracked._")
        out.append("")
    for inst in wl.institutions:
        out.extend(_render_watchlist_institution(inst))

    out.append("### Companies (reference)")
    out.append("")
    out.append("_Reference only — not paper-tracked._")
    out.append("")
    for c in wl.companies:
        loc = c.get("location")
        suffix = " — _{loc}_".format(loc=loc) if loc else ""
        out.append("- **{name}**{suffix}: {note}".format(
            name=c.get("name", ""), suffix=suffix, note=c.get("note", "")
        ))
    if wl.exclusions_note:
        out.append("")
        out.append("> {note}".format(note=wl.exclusions_note))
    out.append("")
    return out


def _render_watchlist_person(person) -> List[str]:
    out: List[str] = []
    if person.status != "resolved":
        out.append("- **{name}** — _unresolved_{note}".format(
            name=person.name,
            note=" ({n})".format(n=person.note) if person.note else "",
        ))
        out.append("")
        return out

    header = "- **{name}**{giant}".format(
        name=person.name, giant=_giant_mark(person.is_giant)
    )
    meta = []
    resolved = person.display_name or person.name
    if resolved and resolved != person.name:
        meta.append("resolved: {r}".format(r=resolved))
    if person.last_institution_name:
        meta.append(person.last_institution_name)
    if person.verify:
        meta.append("**verify affiliation**")
    meta.append("citations {c:,}".format(c=person.cited_by_count))
    meta.append("h-index {h}".format(h=person.h_index))
    if person.note:
        meta.append(person.note)
    out.append(header + " — " + ", ".join(meta))
    if person.papers:
        for paper in person.papers:
            out.append(_watchlist_paper_line(paper))
    else:
        out.append("  - _no recent in-window GenAI papers_")
    out.append("")
    return out


def _render_watchlist_institution(inst) -> List[str]:
    out: List[str] = []
    if getattr(inst, "status", "") == "people-tracked":
        note = getattr(inst, "note", "") or "tracked via people"
        out.append("- **{label}** — _tracked via people_ ({note})".format(
            label=inst.label, note=note
        ))
        out.append("")
        return out
    if inst.status != "resolved":
        out.append("- **{label}** — _unresolved_".format(label=inst.label))
        out.append("")
        return out
    resolved = inst.display_name or ""
    suffix = " (resolved: {r})".format(r=resolved) if resolved else ""
    out.append("- **{label}**{suffix}".format(label=inst.label, suffix=suffix))
    if inst.papers:
        for paper in inst.papers:
            out.append(_watchlist_paper_line(paper))
    else:
        out.append("  - _none in window_")
    out.append("")
    return out


def _render_paper(paper: Paper) -> List[str]:
    title = paper.title or "(untitled)"
    if paper.abs_url:
        header = "#### [{title}]({url})".format(title=title, url=paper.abs_url)
    else:
        header = "#### {title}".format(title=title)
    out = [header]
    out.append(_author_line(paper.authors))
    meta = []
    if paper.date:
        meta.append("date {d}".format(d=paper.date))
    meta.append("signal: {s}".format(s=paper.impact_summary()))
    if paper.has_giant_author:
        meta.append("giant-author paper \U0001F31F")
    if paper.primary_category:
        meta.append("category {c}".format(c=paper.primary_category))
    if paper.source_engines:
        meta.append("via {e}".format(e=", ".join(paper.source_engines)))
    out.append("- " + " | ".join(meta))
    if paper.affiliation_evidence:
        out.append(
            "- affiliation evidence: {ev}".format(
                ev="; ".join(paper.affiliation_evidence[:4])
            )
        )
    links = []
    if paper.abs_url:
        links.append("[abs]({u})".format(u=paper.abs_url))
    if paper.pdf_url:
        links.append("[pdf]({u})".format(u=paper.pdf_url))
    doi_link = _doi_link(paper)
    if doi_link:
        links.append("[doi]({u})".format(u=doi_link))
    if links:
        out.append("- " + " · ".join(links))
    if paper.abstract:
        abstract = paper.abstract.strip()
        if len(abstract) > 1200:
            abstract = abstract[:1200].rstrip() + "…"
        out.append("")
        out.append("> " + abstract.replace("\n", " "))
    return out


def _doi_link(paper: Paper) -> Optional[str]:
    doi = paper.doi_url or paper.doi
    if not doi:
        return None
    if doi.startswith("http"):
        return doi
    return "https://doi.org/" + doi


def render_json(result: Result, generated_at: Optional[str] = None) -> str:
    payload = {
        "window": {"from": result.from_date, "to": result.to_date},
        "generated_at": generated_at,
        "labs": result.labs,
        "per_lab_counts": result.per_lab_counts,
        "people_overall": [a.to_dict() for a in result.people_overall],
        "people_by_lab": {
            k: [a.to_dict() for a in v] for k, v in result.people_by_lab.items()
        },
        "papers": [p.to_dict() for p in result.papers],
    }
    if result.watchlist is not None:
        wl = result.watchlist
        payload["watchlist"] = {
            "people": [p.to_dict() for p in wl.people],
            "people_abroad": [p.to_dict() for p in wl.people_abroad],
            "institutions": [i.to_dict() for i in wl.institutions],
            "companies": wl.companies,
            "exclusions_note": wl.exclusions_note,
        }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def write_reports(
    result: Result,
    out_dir: str,
    fmt: str = "both",
    run_date: Optional[str] = None,
    generated_at: Optional[str] = None,
) -> List[str]:
    """Write requested formats and return the paths written."""

    os.makedirs(out_dir, exist_ok=True)
    days = _window_days(result)
    stamp = run_date or result.to_date
    base = "labpapers_{stamp}_{days}d".format(stamp=stamp, days=days)
    written: List[str] = []

    if fmt in ("md", "both"):
        path = os.path.join(out_dir, base + ".md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(render_markdown(result, generated_at))
        written.append(path)
    if fmt in ("json", "both"):
        path = os.path.join(out_dir, base + ".json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(render_json(result, generated_at))
        written.append(path)
    return written


def _window_days(result: Result) -> int:
    import datetime as _dt

    try:
        frm = _dt.date.fromisoformat(result.from_date)
        to = _dt.date.fromisoformat(result.to_date)
        return (to - frm).days
    except ValueError:
        return 0
