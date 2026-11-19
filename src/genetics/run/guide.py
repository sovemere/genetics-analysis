"""How to read these results: the confidence legend and the reading guide (roadmap M14.3).

One document, built from the engine's own rules and the knowledge pack, and printed by
``genetics cards guide`` and the dashboard's ``/guide`` page alike (AGENTS.md 3: one engine,
two front-ends). It holds no run and no genotype.

**Nothing here restates a threshold.** The score weights, the bands, the frequency
components, every ceiling and both published benchmarks are read from
:mod:`genetics.engine.confidence` and :mod:`genetics.engine.ppv`, and the ceilings are
listed by asking the two functions that apply them (:func:`ceiling_rules`). A threshold
changed there changes here, and a test holds the list to what the functions can return.

**What is authored here** is prose and the published figures it quotes, each with its
source in :data:`SOURCES`. Those were read from the papers' abstracts on 2026-11-19.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from functools import lru_cache
from typing import Any, Final

from genetics.engine import sections
from genetics.engine.cards import (
    Card,
    CardKind,
    EvidenceTier,
    KnowledgePack,
    Replication,
)
from genetics.engine.citations import citation_url
from genetics.engine.confidence import (
    COMMON_FREQUENCY_SCORE,
    EVIDENCE_SCORES,
    FREQUENCY_SCORES,
    QUALITY_CEILINGS,
    RARE_CALL_FREQUENCY_CEILING,
    REPLICATION_SCORES,
    SCORE_BANDS,
    SCORE_WEIGHTS,
    SHARE_CEILINGS,
    UNKNOWN_FREQUENCY_SCORE,
    UNKNOWN_SHARE_CEILING,
    CallSource,
    Ceiling,
    ConfidenceTier,
    polygenic_ceilings,
    single_call_ceilings,
)
from genetics.engine.ppv import CLINICAL_NOTICE, SCOPES, benchmark
from genetics.run.explain import POLYGENIC_ROWS, SINGLE_CALL_ROWS
from genetics.run.reads import STATUS_LABELS

# ---------------------------------------------------------------------------
# The legend
# ---------------------------------------------------------------------------

TIER_LABELS: Final[Mapping[str, str]] = {
    ConfidenceTier.WELL_ESTABLISHED.value: "Well established",
    ConfidenceTier.STRONG.value: "Strong",
    ConfidenceTier.MODERATE.value: "Moderate",
    ConfidenceTier.LIMITED.value: "Limited",
    ConfidenceTier.LIKELY_ARTIFACT.value: "Likely artifact",
}
"""Display text per tier, keyed by the *stored string*. Moved here from ``web.views`` at
M14.3 so that the command prints the same words the badges show."""

TIER_BLURBS: Final[Mapping[str, str]] = {
    ConfidenceTier.WELL_ESTABLISHED.value: (
        "Clinical-guideline or expert-curated evidence, replicated, on a call this array "
        "makes reliably."
    ),
    ConfidenceTier.STRONG.value: "Replicated evidence with a clear effect on a reliable call.",
    ConfidenceTier.MODERATE.value: (
        "Real evidence with a limit somewhere — the effect, the replication, the population "
        "match, or the call itself."
    ),
    ConfidenceTier.LIMITED.value: (
        "Thin evidence, a conflicting literature, or an observation this array is not good "
        "at. Read the breakdown before you read the finding."
    ),
    ConfidenceTier.LIKELY_ARTIFACT.value: (
        "The observation itself is probably wrong, most often a rare heterozygous chip call "
        "or a failed imputation. Shown because hiding it would leave you unable to tell it "
        "from a finding nobody looked for (AGENTS.md §0.1A)."
    ),
}

NO_TIER: Final[str] = "untiered"
"""The group key, URL value and legend key for a card with no tier: every card that did not
match. A real string rather than ``None`` because it is a group heading, a query parameter
and a CSS class at once."""

NO_TIER_LABEL: Final[str] = "No tier"
NO_TIER_BLURB: Final[str] = (
    "Confidence is computed from a finding, so a card with no interpretation has none. Each "
    "of these says why."
)


def _percent(fraction: float) -> str:
    return f"{100 * fraction:g}%"


def _earned_by(tier: ConfidenceTier, rules: list[dict[str, Any]]) -> str:
    """What puts a card at ``tier``, from the bands and the ceilings that cap there."""
    floors = dict(SCORE_BANDS)
    capped = [rule["rule"] for rule in rules if rule["tier"] == tier.value]
    if tier in floors:
        index = [band for band, _ in SCORE_BANDS].index(tier)
        floor = floors[tier]
        if index == 0:
            score = f"A weighted score of {floor:.2f} or more"
        elif floor == 0.0:
            score = f"A weighted score below {SCORE_BANDS[index - 1][1]:.2f}"
        else:
            score = f"A weighted score from {floor:.2f} to below {SCORE_BANDS[index - 1][1]:.2f}"
        sentence = f"{score}, with no ceiling below it."
        if capped:
            sentence += " Or a stronger score held here by a ceiling: " + "; ".join(capped) + "."
        return sentence
    return "No score earns it. Only a ceiling on the observation does: " + "; ".join(capped) + "."


def legend() -> list[dict[str, Any]]:
    """The six badges a card can carry, strongest first, each with what earns it.

    Cheap and pack-free: every dashboard page carries it in the nav.
    """
    rules = ceiling_rules()
    floors = dict(SCORE_BANDS)
    entries = [
        {
            "key": tier.value,
            "label": TIER_LABELS[tier.value],
            "blurb": TIER_BLURBS[tier.value],
            "min_score": floors.get(tier),
            "earned_by": _earned_by(tier, rules),
        }
        for tier in ConfidenceTier
    ]
    entries.append(
        {
            "key": NO_TIER,
            "label": NO_TIER_LABEL,
            "blurb": NO_TIER_BLURB,
            "min_score": None,
            "earned_by": (
                "A card that made no claim: the marker is not on this array, the call failed "
                "or conflicted, a computation did not run, or the question cannot be answered "
                "from a genotyping array. Its status badge names which."
            ),
        }
    )
    return entries


# ---------------------------------------------------------------------------
# The ceilings, asked of the functions that apply them
# ---------------------------------------------------------------------------

_SINGLE: Final[dict[str, Any]] = {
    "has_evidence": True,
    "evidence_tier": EvidenceTier.GWAS,
    "replication": Replication.META_ANALYSIS,
    "population_allele_frequency": 0.3,
    "call_source": CallSource.DIRECT,
    "imputation_quality": None,
    "ancestry_match": 0.9,
    "variant_ancestry": False,
}
"""Single-call inputs that meet no ceiling. Each probe changes one of them."""

_POLYGENIC: Final[dict[str, Any]] = {
    "evidence_tier": EvidenceTier.GWAS,
    "replication": Replication.META_ANALYSIS,
    "weight_coverage": 0.9,
    "weighted_quality": 0.9,
    "ancestry_match": 0.9,
}


def _below(bound: float) -> float:
    return bound * 0.99


def _single_probes() -> list[dict[str, Any]]:
    imputed = {"call_source": CallSource.IMPUTED}
    return [
        {"has_evidence": False, "evidence_tier": None, "replication": None},
        {"evidence_tier": EvidenceTier.ANECDOTAL},
        {"replication": Replication.CONFLICTING},
        {"evidence_tier": EvidenceTier.CANDIDATE_GENE},
        {"population_allele_frequency": _below(RARE_CALL_FREQUENCY_CEILING)},
        {"population_allele_frequency": None},
        imputed,
        *({**imputed, "imputation_quality": _below(bound)} for bound, _ in QUALITY_CEILINGS),
        *({"ancestry_match": _below(bound)} for bound, _ in SHARE_CEILINGS),
        {"ancestry_match": None},
    ]


def _polygenic_probes() -> list[dict[str, Any]]:
    return [
        {"evidence_tier": EvidenceTier.ANECDOTAL},
        {"replication": Replication.CONFLICTING},
        {"evidence_tier": EvidenceTier.CANDIDATE_GENE},
        *({"weighted_quality": _below(bound)} for bound, _ in QUALITY_CEILINGS),
        *({"weight_coverage": _below(bound)} for bound, _ in SHARE_CEILINGS),
        *({"ancestry_match": _below(bound)} for bound, _ in SHARE_CEILINGS),
        {"ancestry_match": None},
    ]


def ceiling_rules() -> list[dict[str, Any]]:
    """Every ceiling a tier can meet, as the engine states it, and which cards it applies to.

    Listed by calling :func:`single_call_ceilings` and :func:`polygenic_ceilings` with inputs
    that meet one rule each, so the rule text and its tier are the engine's own. A test
    holds the list complete against a grid of inputs.
    """
    found: dict[tuple[str, str, str], set[str]] = {}

    def note(ceilings: tuple[Ceiling, ...], applies: str) -> None:
        for ceiling in ceilings:
            found.setdefault((ceiling.input, ceiling.tier.value, ceiling.rule), set()).add(applies)

    for probe in _single_probes():
        note(single_call_ceilings(**(_SINGLE | probe)), "single call")
    for probe in _polygenic_probes():
        note(polygenic_ceilings(**(_POLYGENIC | probe)), "polygenic score")
    order = {tier.value: tier.rank for tier in ConfidenceTier}
    return [
        {
            "input": name,
            "tier": tier,
            "tier_label": TIER_LABELS[tier],
            "rule": rule,
            "applies_to": sorted(applies, reverse=True),
        }
        for (name, tier, rule), applies in sorted(
            found.items(), key=lambda item: (-order[item[0][1]], item[0][0], item[0][2])
        )
    ]


# ---------------------------------------------------------------------------
# Sources quoted on the page
# ---------------------------------------------------------------------------

WEEDON: Final[str] = "10.1136/bmj.n214"
TANDY_CONNOR: Final[str] = "10.1038/gim.2018.38"
OKBAY: Final[str] = "10.1038/s41588-022-01016-z"
DING: Final[str] = "10.1038/s41586-023-06079-4"

SOURCES: Final[tuple[dict[str, str], ...]] = (
    {
        "type": "doi",
        "id": WEEDON,
        "title": (
            "Use of SNP chips to detect rare pathogenic variants: retrospective, population "
            "based diagnostic evaluation (Weedon et al., BMJ 2021)"
        ),
        "supports": (
            "49,908 UK Biobank participants with chip and sequencing data; above 99% "
            "sensitivity, specificity and predictive values for 108,574 common variants; 16% "
            "of 4,757 heterozygous calls below 0.001% frequency confirmed; BRCA1/BRCA2 "
            "positive predictive value 4.2%, sensitivity 34.6%; 20 of 21 Personal Genome "
            "Project participants with at least one false-positive rare pathogenic variant."
        ),
    },
    {
        "type": "doi",
        "id": TANDY_CONNOR,
        "title": (
            "False-positive results released by direct-to-consumer genetic tests highlight "
            "the importance of clinical confirmation testing for appropriate patient care "
            "(Tandy-Connor et al., Genetics in Medicine 2018)"
        ),
        "supports": (
            "49 patient samples sent for clinical confirmation of variants reported in "
            "direct-to-consumer raw data; 40% of those variants were false positives."
        ),
    },
    {
        "type": "doi",
        "id": OKBAY,
        "title": (
            "Polygenic prediction of educational attainment within and between families from "
            "genome-wide association analyses in 3 million individuals (Okbay et al., Nature "
            "Genetics 2022)"
        ),
        "supports": (
            "A polygenic index explaining 12-16% of educational-attainment variance; direct "
            "effects, controlling for parental indices, explain roughly half of its "
            "association."
        ),
    },
    {
        "type": "doi",
        "id": DING,
        "title": (
            "Polygenic scoring accuracy varies across the genetic ancestry continuum (Ding et "
            "al., Nature 2023)"
        ),
        "supports": (
            "Accuracy falls with genetic distance from the training data (Pearson correlation "
            "-0.95, averaged across 84 traits); within European ancestry the farthest decile "
            "of distance had 14% lower accuracy than the nearest."
        ),
    },
)


def _sources() -> list[dict[str, Any]]:
    return [{**source, "url": citation_url(source["type"], source["id"])} for source in SOURCES]


# ---------------------------------------------------------------------------
# The guide
# ---------------------------------------------------------------------------


def _odds_against(fraction: float) -> str:
    return f"about {round((1 - fraction) / fraction)} to 1 against"


def _reading() -> dict[str, Any]:
    return {
        "title": "How to read a card",
        "paragraphs": [
            "Each card states one claim about this genome and carries a confidence tier on "
            "its face, before you open it. The tier says how far to trust the claim. It is "
            "computed from the published evidence and from how well this array observed the "
            "variant, and is never written by hand (AGENTS.md §6).",
            "A low tier is shown, not hidden. A card that is probably a chip artifact sits in "
            "its section looking like one, so that you can tell it from a finding nobody "
            "looked for (AGENTS.md §0.1A). Group or sort by tier to keep a section readable; "
            "nothing is removed.",
            "A card with no tier made no claim. Its status badge says why: the marker is not "
            "on this array, the call failed, or the question cannot be answered from a "
            "genotyping array at all.",
            "Open a card for its evidence: the effect size with its units, the study "
            "population and its size, whether it replicated, and the citations. Under "
            "“Why this tier” it lists each input and says what decided the tier.",
        ],
        "statuses": [{"status": key, "label": label} for key, label in STATUS_LABELS.items()],
    }


_INPUT_LABELS: Final[Mapping[str, str]] = {
    "evidence_tier": "Evidence tier",
    "effect_size": "Effect size",
    "replication": "Replication",
    "allele_frequency": "Population allele frequency",
    "call_quality": "How the call was made",
    "ancestry_match": "Ancestry match to the study",
    "weight_coverage": "Share of the score's weight compared",
    "weighted_quality": "Weighted imputation quality",
}


def _confidence(rules: list[dict[str, Any]]) -> dict[str, Any]:
    bands = ", ".join(
        f"{TIER_LABELS[tier.value].lower()} from {floor:.2f}"
        for tier, floor in SCORE_BANDS
        if floor > 0
    )
    lowest = SCORE_BANDS[-1][0]
    quality = ", ".join(_number(bound) for bound, _ in QUALITY_CEILINGS)
    share = " or ".join(_number(bound) for bound, _ in SHARE_CEILINGS)
    unknown = TIER_LABELS[UNKNOWN_SHARE_CEILING.value].lower()
    return {
        "title": "How a tier is decided",
        "paragraphs": [
            "A tier is the weaker of two things: the band a weighted score falls in, and "
            "every ceiling that applies.",
            "The score adds six inputs. Each is a component from 0 to 1 times a fixed "
            f"weight, and the weights sum to 1. The bands are {bands}, and "
            f"{TIER_LABELS[lowest.value].lower()} below that. No score earns likely "
            "artifact: only a ceiling on the observation does.",
            "A ceiling is the best tier one input allows, whatever the score. Strong "
            "literature cannot raise a weak observation: a well-studied variant called at a "
            "frequency where chip calls are usually wrong is still likely an artifact.",
            "A single-variant card compared with its study population by membership (one "
            "with a saved ancestry comparison), and every HLA card, takes no ancestry "
            "ceiling once the match is known: the match enters the score instead. While it "
            f"is unknown, the cap at {unknown} applies as for any card.",
            "An HLA card also takes its weakest classifier call's ceiling: the quality bounds "
            f"({quality}) applied to the call's posterior, and the bounds {share} applied to "
            "its marker coverage and to the classifier's ancestry match.",
            "For one card of a saved run, genetics runs card <run> <card-id> --json prints "
            "each input's weight, what it cost the score, every ceiling that applies and "
            "which of them set the tier.",
        ],
        "inputs": [
            {
                "single_call": single[0],
                "single_call_label": _INPUT_LABELS[single[0]],
                "polygenic": polygenic[0],
                "polygenic_label": _INPUT_LABELS[polygenic[0]],
                "weight": SCORE_WEIGHTS[single[3]],
            }
            for single, polygenic in zip(SINGLE_CALL_ROWS, POLYGENIC_ROWS, strict=True)
        ],
        "bands": [
            {"tier": tier.value, "label": TIER_LABELS[tier.value], "min_score": floor}
            for tier, floor in SCORE_BANDS
        ],
        "evidence_components": [
            {"evidence_tier": tier.value, "component": score}
            for tier, score in EVIDENCE_SCORES.items()
        ],
        "replication_components": [
            {"replication": value.value, "component": score}
            for value, score in REPLICATION_SCORES.items()
        ],
        "ceilings": rules,
    }


def _number(value: float) -> str:
    return f"{value:.2f}"


def _caps(bounds: Any) -> str:
    """``below 0.80 caps the tier at moderate, below 0.60 at limited, ...``, loosest first."""
    parts = [(bound, TIER_LABELS[tier.value].lower()) for bound, tier in bounds][::-1]
    first, *rest = parts
    words = [f"below {first[0]} caps the tier at {first[1]}"]
    words += [f"below {bound} at {tier}" for bound, tier in rest]
    return ", ".join(words[:-1]) + " and " + words[-1] if len(words) > 1 else words[0]


def _rarity() -> dict[str, Any]:
    rare, brca = (benchmark(scope) for scope in SCOPES)
    components: list[dict[str, Any]] = []
    lower: float | None = None
    for bound, component in FREQUENCY_SCORES:
        components.append({"from": lower, "below": bound, "component": component})
        lower = bound
    components.append({"from": lower, "below": None, "component": COMMON_FREQUENCY_SCORE})
    common = _percent(FREQUENCY_SCORES[-1][0])
    band = _percent(RARE_CALL_FREQUENCY_CEILING)
    return {
        "title": "Rarity lowers confidence",
        "paragraphs": [
            "The intuition that a rare hit is a big finding is backwards for a genotyping "
            "array. The rarer a variant is in the population, the more likely the array's "
            "call of it is wrong (AGENTS.md §4.1).",
            "Weedon et al. compared chip calls with sequencing in 49,908 UK Biobank "
            "participants. For 108,574 common variants, sensitivity, specificity and both "
            "predictive values were above 99%. Below 0.001% population frequency, only "
            f"{_percent(rare['estimate'])} of 4,757 heterozygous chip calls were confirmed: "
            f"{_odds_against(rare['estimate'])}. For pathogenic BRCA1 and BRCA2 variants the "
            f"positive predictive value was {_percent(brca['estimate'])}, "
            f"{_odds_against(brca['estimate'])}. In consumer-array data from the Personal "
            "Genome Project, 20 of 21 people had at least one false-positive rare pathogenic "
            "variant.",
            "A clinical laboratory that checked the variants reported in 49 patients' "
            "direct-to-consumer raw data found 40% of those variants were false positives "
            "(Tandy-Connor et al. 2018).",
            "So population allele frequency is a confidence input, and it runs the other way "
            f"from intuition: its component is {COMMON_FREQUENCY_SCORE:g} for a variant at "
            f"{common} or more and 0 below {band}, and below {band} the tier is capped at "
            "likely artifact whatever the literature says. With no population frequency the "
            f"component is {UNKNOWN_FREQUENCY_SCORE:g} and the tier is capped at moderate, "
            "because an absence cannot show that a call is common.",
            "A card in that band states the benchmark on its face. The benchmarks were "
            "measured for heterozygous calls on UK Biobank's array. They are not calibrated "
            "for this vendor, for homozygous or hemizygous calls, or for imputed calls, and "
            f"they are not a personal probability. {CLINICAL_NOTICE}",
            "Imputation does not fix this. An imputed rare variant inherits the unreliability "
            "of the markers it was inferred from, plus the imputation's own error, so it stays "
            "frequency-gated.",
        ],
        "frequency_components": components,
        "unknown_frequency_component": UNKNOWN_FREQUENCY_SCORE,
        "rare_call_band": RARE_CALL_FREQUENCY_CEILING,
        "benchmarks": [rare, brca],
    }


def _polygenic(cards: list[Card]) -> dict[str, Any]:
    scores = [card for card in cards if card.kind is CardKind.POLYGENIC]
    european_only = sum(
        1
        for card in scores
        if card.evidence is not None and {a.value for a in card.evidence.ancestry} == {"EUR"}
    )
    with_attenuation = sum(
        1
        for card in scores
        if card.evidence is not None and card.evidence.within_family_attenuation is not None
    )
    quality = _caps((_number(bound), tier) for bound, tier in QUALITY_CEILINGS)
    share = _caps((_percent(bound), tier) for bound, tier in SHARE_CEILINGS)
    unknown = TIER_LABELS[UNKNOWN_SHARE_CEILING.value].lower()
    attenuation = (
        "No polygenic card in this pack has a published within-family estimate for its own "
        "weights, and none borrows another model's; each says so on its face."
        if with_attenuation == 0
        else f"{with_attenuation} of {len(scores)} polygenic cards in this pack state a "
        "published within-family estimate for their own weights; the rest say on their face "
        "that none is known, and none borrows another model's."
    )
    return {
        "title": "What a polygenic score can say",
        "paragraphs": [
            "A polygenic score adds up many small effects. Four things limit what one says "
            "about a person, and each is on the card.",
            "Coverage. A score's weights were fitted on variants this array may not carry. "
            "The card states the share of the score's weight that was compared, before and "
            f"after imputation. A share {share}. Each imputed variant enters with its "
            f"imputation quality, and a weighted quality {quality}.",
            "Portability. Scores lose accuracy away from the ancestry they were trained in. "
            "Ding et al. 2023 found accuracy fell steadily with genetic distance from the "
            "training data (correlation -0.95 across 84 traits); even within European "
            "ancestry, the farthest tenth had 14% lower accuracy than the nearest. Ancestry "
            "placement runs before any score, and an ancestry match to the study "
            f"{share}; an unknown match caps it at {unknown}. "
            f"{european_only} of {len(scores)} polygenic cards in this pack were trained in "
            "European-ancestry cohorts alone.",
            "Within-family attenuation. A population association mixes a direct effect with "
            "family environment, assortative mating and population structure. In EA4 "
            "(Okbay et al. 2022, about 3 million people) a polygenic index explained 12-16% "
            "of the variance in educational attainment, and direct effects, estimated "
            f"against parents' scores, were roughly half of its association. {attenuation}",
            "Position, not prediction. A score is shown as where it falls in a reference "
            "distribution, with the width of the distribution drawn wider than the point. "
            "Where the cited study reports outcome rates by score decile they are shown "
            "beside it; otherwise no absolute risk is given.",
        ],
        "cards": [
            {
                "card_id": card.id,
                "section": card.section.value,
                "section_title": sections.get(card.section.value).title,
                "title": card.title,
                "study_ancestry": (
                    [] if card.evidence is None else [a.value for a in card.evidence.ancestry]
                ),
                "within_family_attenuation": (
                    None if card.evidence is None else card.evidence.within_family_attenuation
                ),
                "decile_outcomes": card.decile_outcomes is not None,
            }
            for card in scores
        ],
    }


_LIMITS: Final[tuple[tuple[str, str], ...]] = (
    (
        "Rare variants",
        "See “Rarity lowers confidence”. The array covers many ClinVar positions; "
        "coverage is not the problem, the reliability of a rare call is (AGENTS.md §4.1).",
    ),
    (
        "Insertions and deletions",
        "An indel is written I or D with no sequence recorded, so which allele is the "
        "reference cannot be read from the file. Indels are left out of allele matching, "
        "and a card that would need one says “Indel excluded” (AGENTS.md §4.2).",
    ),
    (
        "One copy of X and Y",
        "A call on a single-copy X or Y is written as two identical letters, like a "
        "homozygote. Sex is inferred from X heterozygosity and the Y call rate, and X and Y "
        "are then read as one copy; a two-letter mixed call at a one-copy site is flagged "
        "“Heterozygous at a haploid locus” (AGENTS.md §2).",
    ),
    (
        "Copy number and structure",
        "Deletions, duplications and rearrangements of whole genes are invisible to a SNP "
        "array: SMN1, RHD, the alpha-globin genes and CYP2D6 hybrids among them. A carrier "
        "result is therefore incomplete in a way that cannot be seen unless it is stated, "
        "and the reproductive section states it (AGENTS.md §3.2).",
    ),
    (
        "Mitochondrial and Y lineages",
        "The array carries a subset of mtDNA and Y sites, so haplogroups are coarse clades, "
        "not fine subclades. Each call gives the markers that support it beside how many of "
        "this array's markers sit on a defining site at all; the ancestry page shows both "
        "(AGENTS.md §4.7).",
    ),
    (
        "Imputation",
        "Imputation infers common variants the array did not type from a reference panel. "
        "Each imputed value carries a quality score, and a poor one lowers its card's tier. "
        "It does not make a rare call reliable (AGENTS.md §4.3).",
    ),
)


def _array(cards: list[Card]) -> dict[str, Any]:
    impossible = [card for card in cards if card.kind is CardKind.IMPOSSIBILITY]
    return {
        "title": "What this array cannot tell you",
        "paragraphs": [
            "A consumer array reads a fixed set of positions chosen in advance, and two "
            "letters at each. That sets limits no amount of analysis removes.",
            "Some questions cannot be answered from a genotyping array at all. Each has a "
            "card in the section where you would look for it, so that its absence is not "
            "read as a clear result.",
        ],
        "limits": [{"title": title, "text": text} for title, text in _LIMITS],
        "not_determinable": [
            {
                "card_id": card.id,
                "section": card.section.value,
                "section_title": sections.get(card.section.value).title,
                "title": card.title,
                "reason": card.impossibility_reason,
            }
            for card in impossible
        ],
    }


def reading_guide(pack: KnowledgePack) -> dict[str, Any]:
    """The whole guide: what ``genetics cards guide --json`` prints after its schema tag."""
    cards = list(pack.cards)
    rules = ceiling_rules()
    return {
        "legend": legend(),
        "reading": _reading(),
        "confidence": _confidence(rules),
        "rarity": _rarity(),
        "polygenic": _polygenic(cards),
        "array": _array(cards),
        "sources": _sources(),
    }


@lru_cache(maxsize=1)
def _committed_text() -> str:
    return json.dumps(reading_guide(KnowledgePack.load(None)))


def committed_guide() -> dict[str, Any]:
    """:func:`reading_guide` for the committed pack, built once per process. A fresh copy
    each call, so a caller cannot change what the next one reads."""
    loaded: dict[str, Any] = json.loads(_committed_text())
    return loaded


__all__ = [
    "NO_TIER",
    "NO_TIER_BLURB",
    "NO_TIER_LABEL",
    "SOURCES",
    "TIER_BLURBS",
    "TIER_LABELS",
    "ceiling_rules",
    "committed_guide",
    "legend",
    "reading_guide",
]
