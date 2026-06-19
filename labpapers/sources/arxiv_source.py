"""arXiv affiliation source: a recent candidate pool resolved to labs.

A light adapter around the existing arXiv candidate pool + ``affiliations.resolve``
path. This is the primary path for the labs OpenAlex cannot tag by institution
id (Anthropic via the arxiv.org/html fallback, DeepSeek via the collective
byline / affiliation strings), and it also catches the very freshest papers for
every lab before OpenAlex indexes them.
"""

from __future__ import annotations

from typing import List

from ..model import Paper
from . import affiliations, arxiv
from .base import FetchContext, topic_filter


class ArxivAffiliationSource:
    name = "arxiv-affiliation"

    def fetch(self, ctx: FetchContext) -> List[Paper]:
        candidates = arxiv.recent_candidates(
            ctx.client,
            ctx.categories,
            ctx.from_date,
            max_pages=ctx.max_pages,
            delay=ctx.arxiv_delay,
        )
        # Topic-filter BEFORE the expensive affiliation step.
        candidates = [p for p in candidates if topic_filter(p, ctx.require_keyword)]

        resolutions = affiliations.resolve(
            ctx.client,
            candidates,
            mailto=ctx.mailto,
            fetch_html=ctx.fulltext,
            concurrency=ctx.concurrency,
            cache=ctx.cache,
            only=ctx.lab_keys,
        )

        out: List[Paper] = []
        for paper in candidates:
            res = resolutions.get(paper.arxiv_id)
            if not res or not res.labs:
                continue
            paper.labs_matched = sorted(set(res.labs))
            paper.affiliation_evidence = res.evidence[:8]
            paper.resolved_via = res.resolved_via
            if res.authors:
                # OpenAlex authors carry ids + affiliations; prefer them.
                paper.authors = res.authors
            if res.resolved_via and res.resolved_via not in paper.source_engines:
                paper.source_engines.append("affiliation:" + res.resolved_via)
            out.append(paper)
        return out
