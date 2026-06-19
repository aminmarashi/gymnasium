"""OpenAlex institution source: works authored at a covered lab's institutions.

A light adapter around the existing ``openalex.works_by_institutions`` path. It
covers the labs OpenAlex tags cleanly by institution id (Google incl. DeepMind,
Meta, OpenAI, Zhipu); Anthropic and DeepSeek have no usable institution id and
are handled by the arXiv-affiliation and site sources instead.
"""

from __future__ import annotations

from typing import List

from .. import config
from ..model import Paper
from . import affiliations, openalex
from .base import FetchContext, topic_filter


class OpenAlexInstitutionSource:
    name = "openalex-institution"

    def fetch(self, ctx: FetchContext) -> List[Paper]:
        labs = config.selected_labs(ctx.lab_keys)
        covered_ids = config.all_institution_ids(labs.values())
        if not covered_ids:
            return []
        works = openalex.works_by_institutions(
            ctx.client, covered_ids, ctx.from_date, ctx.to_date, ctx.mailto
        )
        out: List[Paper] = []
        for work in works:
            paper = openalex.normalize_work(work)
            paper.source_engines = ["openalex-institutions"]
            matched, evidence = affiliations.labs_from_authors(
                paper.authors, ctx.lab_keys
            )
            paper.labs_matched = sorted(matched)
            paper.affiliation_evidence = evidence[:8]
            paper.resolved_via = "openalex"
            if paper.labs_matched and topic_filter(paper, ctx.require_keyword):
                out.append(paper)
        return out
