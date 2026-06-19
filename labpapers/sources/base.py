"""Source-agnostic plumbing: the LabSource protocol and a shared fetch context.

The pipeline does not care WHERE papers come from -- arXiv, OpenAlex, or a lab's
own publications site. Every source implements ``LabSource`` and returns ``Paper``
records already tagged with the lab(s) it covers; the pipeline unions, dedups,
and runs the shared prominence + scoring + report over the result.

``topic_filter`` lives here (not in pipeline) so both the pipeline and the
individual sources can apply the GenAI scope check without a circular import.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

try:  # Protocol is stdlib on 3.8+, but guard for very old typing backports.
    from typing import Protocol, runtime_checkable
except ImportError:  # pragma: no cover
    from typing_extensions import Protocol, runtime_checkable

from .. import config
from ..cache import Cache
from ..http import HttpClient
from ..model import Paper


@dataclass
class FetchContext:
    """Everything a source needs for one run: the window, the selected labs, and
    the shared HTTP client / cache plus the relevant run options."""

    from_date: str
    to_date: str
    lab_keys: List[str]
    client: HttpClient
    cache: Cache
    mailto: Optional[str] = None
    categories: List[str] = field(default_factory=list)
    require_keyword: bool = True
    fulltext: bool = True
    concurrency: int = 6
    max_pages: int = 10
    arxiv_delay: float = 3.0


@runtime_checkable
class LabSource(Protocol):
    """A source of lab-tagged papers for a given window."""

    name: str

    def fetch(self, ctx: FetchContext) -> List[Paper]:
        ...


def topic_filter(paper: Paper, require_keyword: bool = True) -> bool:
    """Whether a paper passes the GenAI topic filter.

    The PRIMARY signal is structured (``config.classify_topic``): OpenAlex works
    are classified on their primary_topic field/subfield, arXiv works on their
    primary category, and a domain-phrase backstop catches ML-applied-to-domain
    cross-lists. A structured EXCLUDE verdict always wins -- it overrides any
    GenAI keyword hit, which is what finally closes the keyword-leak class
    (protein folding, traffic forecasting, steel-defect Transformers, ...).

    ``require_keyword=False`` (the ``--no-keyword-filter`` escape hatch) disables
    topic filtering entirely and passes everything, unchanged.
    """

    if not require_keyword:
        return True

    verdict = config.classify_topic(paper)
    if verdict == config.EXCLUDE:
        return False
    if verdict == config.KEEP:
        return True
    # Inconclusive structure -> the GenAI keyword set is the secondary booster.
    # The OpenAlex primary_topic name is scanned alongside title + abstract so a
    # clearly-GenAI topic ("Text Generation", "Multimodal ...") still keeps a
    # record whose abstract is terse, without re-admitting non-GenAI CS topics
    # (crypto / quantum / Bayesian methods carry no GenAI keyword in their names).
    text = " ".join((
        paper.title or "",
        paper.abstract or "",
        paper.primary_topic or "",
    ))
    return config.has_genai_keyword(text)
