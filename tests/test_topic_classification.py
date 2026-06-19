"""Structured GenAI topic classification: keep real GenAI, exclude domain leaks.

These are the regression tests for the topic-leak class of bug. The keyword
filter kept admitting ML-applied-to-another-domain papers (a Google-affiliated
co-author on a protein-folding / traffic / steel-defect paper still tripped a
broad term like "generative" or "transformer-based"). The fix classifies on the
structured signal -- OpenAlex primary_topic field/subfield, arXiv primary
category -- and a domain-phrase backstop, with EXCLUDE always beating a keyword.

Every leaked title from the committed reports is asserted EXCLUDED here, and a
representative set of genuine GenAI papers is asserted KEPT. No live network.
"""

from labpapers import config, pipeline
from labpapers.model import Paper
from labpapers.sources import openalex


def _oa(title, abstract="", field=None, subfield=None, topic=None, topic_fields=None):
    """An OpenAlex-shaped paper: no arXiv category, structured topic instead."""
    return Paper(
        title=title,
        abstract=abstract,
        primary_field=field,
        primary_subfield=subfield,
        primary_topic=topic,
        topic_fields=topic_fields or ([field] if field else []),
        source_engines=["openalex-institutions"],
    )


def _arxiv(title, abstract="", primary_category=None, categories=None):
    return Paper(
        title=title,
        abstract=abstract,
        primary_category=primary_category,
        categories=categories or ([primary_category] if primary_category else []),
        source_engines=["arxiv"],
    )


def _excluded(paper):
    return (
        config.classify_topic(paper) == config.EXCLUDE
        and not pipeline.topic_filter(paper, require_keyword=True)
    )


def _kept(paper):
    return pipeline.topic_filter(paper, require_keyword=True)


# ---------------------------------------------------------------------------
# Leaked non-GenAI titles -> EXCLUDED (the exact bug each round reintroduced)
# ---------------------------------------------------------------------------
def test_protein_folding_paper_excluded():
    # Biology field. Title/abstract carry "generative"/"diffusion-based", which
    # used to leak it in; the biochem field + "protein folding" phrase win now.
    p = _oa(
        "Exploring the conformational landscape of adenylate kinase and beyond "
        "with protein folding models",
        abstract="Diffusion-based generative models sample protein conformations.",
        field="Biochemistry, Genetics and Molecular Biology",
        subfield="Molecular Biology",
        topic="Protein Structure and Dynamics",
        topic_fields=["Biochemistry, Genetics and Molecular Biology", "Computer Science"],
    )
    assert _excluded(p)


def test_protein_folding_excluded_even_if_misfiled_as_ai():
    # Worst case: OpenAlex mis-files the ML-for-bio paper under CS/AI. The
    # domain-phrase backstop still excludes it.
    p = _oa(
        "Protein folding with denoising diffusion models",
        abstract="A generative model for protein structure prediction.",
        field="Computer Science",
        subfield="Artificial Intelligence",
        topic="Machine Learning Applications",
    )
    assert _excluded(p)


def test_traffic_forecasting_papers_excluded():
    smart = _oa(
        "SMART: Spatio-Temporal Attention-based Large Language Model for "
        "Real-Time Traffic Prediction",
        abstract="We predict urban traffic flow with a transformer model.",
        field="Engineering",
        subfield="Civil and Structural Engineering",
        topic="Traffic Prediction and Management",
    )
    gnn = _oa(
        "A Cloud-Based Spatio-Temporal GNN-Transformer Hybrid Model for Traffic "
        "Flow Forecasting with External Feature Integration",
        abstract="Traffic flow forecasting with a transformer architecture.",
        field="Engineering",
        subfield="Transportation",
        topic="Traffic and Network Flow Models",
    )
    # Both literally contain "Large Language Model" / "transformer" keywords.
    assert config.has_genai_keyword(smart.title + " " + smart.abstract)
    assert _excluded(smart)
    assert _excluded(gnn)


def test_steel_defect_transformer_paper_excluded():
    p = _oa(
        "Feature-Embedded Transformer-Based Classification of Steel Plate "
        "Defects for Robust Industrial Process Inspection",
        abstract="A feature-embedded Transformer encoder classifies steel plate "
        "defects for industrial process inspection.",
        field="Materials Science",
        subfield="Metals and Alloys",
        topic="Advanced Steel Processing Technologies",
    )
    assert config.has_genai_keyword(p.title + " " + p.abstract)  # "transformer-based"
    assert _excluded(p)


def test_origins_of_life_catalytic_polymer_paper_excluded():
    p = _oa(
        "Conditions Enabling the Persistence of Cooperating Synthetase, Ligase, "
        "and Mutation-Inhibitor Catalytic Polymers",
        abstract="In origins-of-life research, slower diffusion promotes "
        "multilevel selection of catalytic polymers.",
        field="Biochemistry, Genetics and Molecular Biology",
        subfield="Molecular Biology",
        topic="Origins of Life and Prebiotic Chemistry",
    )
    assert _excluded(p)


def test_k_median_clustering_theory_paper_excluded():
    p = _oa(
        "A Constant-Factor Approximation Algorithm for k-Median in Sublinear Time",
        abstract="We give an approximation algorithm for the k-median clustering "
        "problem with sublinear running time.",
        field="Mathematics",
        subfield="Discrete Mathematics and Combinatorics",
        topic="Approximation Algorithms and Complexity",
    )
    assert _excluded(p)


def test_pe_means_dp_clustering_paper_excluded():
    # DP k-means clustering via "Private Evolution". OpenAlex files it under
    # CS/Artificial Intelligence with a "Privacy-Preserving Technologies" topic,
    # and the incidental "synthetic data generation" phrase tripped the keyword
    # booster -- so it leaked into the institution scan. It carries NO generative-
    # model signal, so the conditional privacy/clustering backstop now EXCLUDEs it.
    p = _oa(
        "PE-means: Improved Differentially Private $k$-means Clustering through "
        "Private Evolution",
        abstract="We study the problem of differentially private (DP) $k$-means "
        "clustering in Euclidean space. We introduce PE-means, an extension of "
        "the private evolution (PE) algorithm (a popular method for synthetic "
        "data generation), to clustering, with new evolutionary operators.",
        field="Computer Science",
        subfield="Artificial Intelligence",
        topic="Privacy-Preserving Technologies in Data",
    )
    # The incidental "data generation" booster still fires...
    assert config.has_genai_keyword(p.title + " " + p.abstract)
    # ...but there is no generative-MODEL signal, so it is EXCLUDED.
    assert not config.has_generative_model_signal(p.title + " " + p.abstract)
    assert _excluded(p)


def test_dp_image_synthesis_paper_kept():
    # A genuinely generative privacy paper (DP fine-tuning for image synthesis)
    # carries a generative-model signal, so the conditional backstop does NOT
    # fire and it is kept -- the conditional exclude must not over-reach.
    p = _oa(
        "DP-SAPF: Saliency-Aware Parameter Fine-tuning of Public Models for "
        "Differentially Private Image Synthesis",
        abstract="We fine-tune public diffusion models for differentially "
        "private image synthesis.",
        field="Computer Science",
        subfield="Artificial Intelligence",
        topic="Privacy-Preserving Technologies in Data",
    )
    assert config.has_generative_model_signal(p.title + " " + p.abstract)
    assert _kept(p)


def test_llm_privacy_synthetic_data_paper_kept():
    # Privacy-preserving synthetic data auditing that is explicitly about LLMs /
    # generative AI: the "language model" signal rescues it from the backstop.
    p = _oa(
        "Auditing Disclosures in Synthetic Data",
        abstract="The rapid adoption of generative AI and Large Language Models "
        "(LLMs) has spurred interest in synthetic data as a privacy-preserving "
        "alternative to sensitive datasets.",
        field="Computer Science",
        subfield="Artificial Intelligence",
        topic="Privacy-Preserving Technologies in Data",
    )
    assert _kept(p)


def test_marl_social_dilemmas_paper_excluded():
    # Multi-Agent Reinforcement Learning / Sequential Social Dilemmas: classical
    # game-theory RL, NOT GenAI. It leaked into the 30-day report purely on the
    # bare "agent" booster word. The booster now admits only QUALIFIED GenAI agent
    # phrases ("LLM agent", "agentic AI", "tool-using", ...), so this RL paper --
    # whose only "GenAI" hits were "agent"/"agents" -- is dropped. The structured
    # signal is inconclusive (CS/AI), so the kept-set decision is the booster's.
    p = _oa(
        "Fairness over Equality: Correcting Social Incentives in Asymmetric "
        "Sequential Social Dilemmas",
        abstract="Sequential Social Dilemmas (SSDs) provide a key framework for "
        "studying how cooperation emerges when individual incentives conflict "
        "with collective welfare. In Multi-Agent Reinforcement Learning, these "
        "problems are addressed by incorporating intrinsic drives that encourage "
        "prosocial or fair behavior. Most existing methods assume that agents "
        "face identical incentives and require global information to assess "
        "fairness. We introduce asymmetric variants of well-known SSD "
        "environments, redefine fairness by accounting for agents' reward "
        "ranges, add an agent-based weighting mechanism, and localize social "
        "feedback for partial observability.",
        field="Computer Science",
        subfield="Artificial Intelligence",
        topic="Game Theory and Multi-Agent Systems",
    )
    assert config.classify_topic(p) == config.UNKNOWN
    assert not config.has_genai_keyword(p.title + " " + p.abstract)
    assert not _kept(p)


def test_condensed_matter_physics_paper_excluded():
    p = _oa(
        "Tensor Network Representations of Frustrated Quantum Magnets",
        abstract="We study condensed matter quantum many-body systems with "
        "tensor network states.",
        field="Physics and Astronomy",
        subfield="Condensed Matter Physics",
        topic="Quantum Many-Body Systems",
    )
    assert _excluded(p)


# ---------------------------------------------------------------------------
# EXCLUDE always beats a keyword hit
# ---------------------------------------------------------------------------
def test_exclude_field_overrides_genai_keyword():
    # A medical paper that genuinely contains a GenAI keyword ("foundation
    # model") is still excluded by its Medicine field under STRICT scope.
    p = _oa(
        "A foundation model for retinal disease screening",
        abstract="We train a vision foundation model on fundus images.",
        field="Medicine",
        subfield="Ophthalmology",
        topic="Retinal Imaging and Disease",
    )
    assert config.has_genai_keyword(p.title + " " + p.abstract)
    assert _excluded(p)


# ---------------------------------------------------------------------------
# Genuine GenAI papers -> KEPT
# ---------------------------------------------------------------------------
def test_llm_paper_kept():
    p = _oa(
        "Scaling Instruction-Tuned Language Models for Reasoning",
        abstract="We study reasoning in large language models.",
        field="Computer Science",
        subfield="Artificial Intelligence",
        topic="Natural Language Processing",
    )
    # Not a structural KEEP (the AI subfield is too coarse to confirm GenAI on its
    # own) -- the GenAI keyword booster is what keeps it.
    assert config.classify_topic(p) == config.UNKNOWN
    assert _kept(p)


def test_diffusion_image_paper_kept():
    p = _oa(
        "Latent Diffusion Models for High-Resolution Image Synthesis",
        abstract="A latent diffusion model for controllable image generation.",
        field="Computer Science",
        subfield="Computer Vision and Pattern Recognition",
        topic="Generative Models and Image Synthesis",
    )
    assert _kept(p)


def test_agents_paper_kept():
    p = _oa(
        "Tool-Using LLM Agents for Multi-Step Reasoning",
        abstract="We build agents that call tools and plan over many steps.",
        field="Computer Science",
        subfield="Artificial Intelligence",
        topic="Autonomous Agents and Planning",
    )
    assert _kept(p)


def test_vlm_paper_kept():
    p = _oa(
        "A Vision-Language Foundation Model for Open-Vocabulary Detection",
        abstract="A multimodal vision-language model for open-vocabulary tasks.",
        field="Computer Science",
        subfield="Computer Vision and Pattern Recognition",
        topic="Multimodal Learning",
    )
    assert _kept(p)


def test_genai_topic_name_keeps_terse_record():
    # A record with a terse abstract but a clearly-GenAI primary_topic name is
    # kept: the topic name is scanned alongside title + abstract.
    p = _oa(
        "MoEStream",
        abstract="",
        field="Computer Science",
        subfield="Artificial Intelligence",
        topic="Text Generation and Language Models",
    )
    assert _kept(p)


# ---------------------------------------------------------------------------
# Non-GenAI computer science (crypto / quantum / theory / statistics) -> DROPPED
# OpenAlex files all of these under the coarse "Artificial Intelligence"
# subfield, so a subfield-only keep would re-admit them. They carry no GenAI
# keyword, so the keyword booster drops them under STRICT GenAI scope.
# ---------------------------------------------------------------------------
def test_non_genai_cs_papers_dropped():
    crypto = _oa(
        "30+ Years of Malicious Cryptography",
        abstract="A survey of cryptovirology and kleptographic attacks.",
        field="Computer Science", subfield="Artificial Intelligence",
        topic="Cryptographic Implementations and Security",
    )
    quantum = _oa(
        "No Exponential Quantum Speedup for SIS Anymore",
        abstract="A quantum algorithm for the short integer solution problem.",
        field="Computer Science", subfield="Artificial Intelligence",
        topic="Quantum Computing Algorithms and Architecture",
    )
    bayes = _oa(
        "Dirichlet process mixtures of block g priors for model selection",
        abstract="Bayesian model selection and prediction in linear models.",
        field="Computer Science", subfield="Artificial Intelligence",
        topic="Bayesian Methods and Mixture Models",
    )
    theory = _oa(
        "PAC Learning with Bandit Feedback: Sharp Sample Complexity",
        abstract="We characterize the sample complexity of realizable PAC "
        "learning with bandit feedback.",
        field="Computer Science", subfield="Artificial Intelligence",
        topic="Machine Learning and Algorithms",
    )
    for paper in (crypto, quantum, bayes, theory):
        assert config.classify_topic(paper) == config.UNKNOWN, paper.title
        assert not _kept(paper), paper.title


def test_logic_programming_paper_excluded_despite_reasoning_agent_keywords():
    # Datalog-style declarative logic programming leaked on "reasoning"/"agent".
    # The "logic programming language" backstop excludes it (EXCLUDE > keyword).
    diamonds = _oa(
        "Diamonds Are Forever: Stabilization Semantics for Unrestricted "
        "Aggregation and Recursion in Logica",
        abstract="Logica is an open-source logic programming language that "
        "compiles to SQL; it combines recursion and aggregation for reasoning "
        "from shortest paths to PageRank.",
        field="Computer Science", subfield="Computational Theory and Mathematics",
        topic="Logic, Reasoning, and Knowledge",
    )
    robots = _oa(
        "Logical Robots: Declarative Multi-Agent Programming in Logica",
        abstract="An agentic AI demo where robot behavior is specified "
        "declaratively in the logic programming language Logica via predicates.",
        field="Computer Science", subfield="Computational Theory and Mathematics",
        topic="Logic, Reasoning, and Knowledge",
    )
    # "agentic AI" hits the keyword booster, yet the logic-programming-language
    # backstop still EXCLUDEs it (EXCLUDE > keyword).
    assert config.has_genai_keyword(robots.title + " " + robots.abstract)
    assert _excluded(diamonds)
    assert _excluded(robots)


def test_cs_work_with_keyword_but_non_ai_subfield_kept_via_booster():
    # A retrieval-augmented paper OpenAlex files under Information Systems (not an
    # auto-keep subfield) is rescued by the GenAI keyword booster.
    p = _oa(
        "Retrieval-Augmented Generation for Enterprise Question Answering",
        abstract="A retrieval-augmented LLM pipeline over enterprise documents.",
        field="Computer Science",
        subfield="Information Systems",
        topic="Information Retrieval and Search",
    )
    assert config.classify_topic(p) == config.UNKNOWN
    assert _kept(p)


# ---------------------------------------------------------------------------
# arXiv category gating + cross-list domain backstop
# ---------------------------------------------------------------------------
def test_arxiv_primary_category_outside_scope_excluded():
    p = _arxiv(
        "Protein structure prediction with equivariant networks",
        abstract="An equivariant network for protein folding.",
        primary_category="q-bio.BM",
        categories=["q-bio.BM", "cs.LG"],
    )
    assert _excluded(p)


def test_arxiv_cs_crosslist_on_other_domain_excluded_by_phrase():
    # Primary category is in scope (cs.LG) but the work is ML applied to traffic.
    p = _arxiv(
        "Deep Learning for Traffic Flow Forecasting",
        abstract="A transformer model for traffic flow forecasting on highways.",
        primary_category="cs.LG",
        categories=["cs.LG"],
    )
    assert _excluded(p)


def test_arxiv_cs_cl_always_kept():
    p = _arxiv("Any NLP paper", abstract="no obvious keyword here",
               primary_category="cs.CL", categories=["cs.CL"])
    assert config.classify_topic(p) == config.KEEP
    assert _kept(p)


def test_arxiv_cs_lg_requires_keyword():
    no_kw = _arxiv("A study of tabular data", abstract="trees and forests",
                   primary_category="cs.LG", categories=["cs.LG"])
    with_kw = _arxiv("A study of language model pretraining",
                     abstract="we pretrain a large language model",
                     primary_category="cs.LG", categories=["cs.LG"])
    assert config.classify_topic(no_kw) == config.UNKNOWN
    assert not _kept(no_kw)
    assert _kept(with_kw)


def test_no_keyword_filter_is_a_full_bypass():
    # The --no-keyword-filter escape hatch disables topic filtering entirely.
    p = _arxiv("grid solver", abstract="finite elements",
               primary_category="math.NA", categories=["math.NA"])
    assert pipeline.topic_filter(p, require_keyword=False)


# ---------------------------------------------------------------------------
# normalize_work wiring: topic fields are extracted and drive the filter
# ---------------------------------------------------------------------------
def test_works_select_requests_topic_fields():
    assert "primary_topic" in openalex.WORKS_SELECT
    assert "topics" in openalex.WORKS_SELECT


def test_normalize_work_extracts_topic_and_excludes(fixture):
    work = fixture("openalex_work_protein.json")
    paper = openalex.normalize_work(work)
    assert paper.primary_field == "Biochemistry, Genetics and Molecular Biology"
    assert paper.primary_subfield == "Molecular Biology"
    assert paper.primary_topic == "Protein Structure and Dynamics"
    # union of all topic fields includes the secondary CS topic
    assert "Computer Science" in paper.topic_fields
    # primary field is biology, so the work is excluded despite the CS topic
    assert _excluded(paper)


def test_normalize_work_genai_paper_kept(fixture):
    work = fixture("openalex_work.json")
    paper = openalex.normalize_work(work)
    # The base fixture has no topic block -> structured signal is inconclusive,
    # so the GenAI keyword ("language models") keeps it (legacy behaviour holds).
    assert config.classify_topic(paper) == config.UNKNOWN
    assert _kept(paper)
