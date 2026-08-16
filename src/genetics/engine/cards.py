"""The card schema (roadmap M3.1, AGENTS.md 3 "Cards are data, not code").

A card is a declarative record: what to match, what each genotype means, what the evidence
is, and where it came from. The engine evaluates cards; adding a finding means adding a
knowledge-pack entry with sources, not writing a module.

Validation is strict and happens at load, on the same reasoning as
:mod:`genetics.refs.manifest`: this is a hand-authored format, and a typo that survives to
render time produces a confident, wrong, personal claim -- the failure AGENTS.md 6 opens
with. Unknown keys are rejected everywhere rather than ignored, because in a format with
optional fields a silently-ignored key is indistinguishable from one that had no effect.

Five rules here are load-bearing. Each is a place where the obvious permissive alternative
fails quietly rather than loudly.

**A card cannot state its own confidence.** ``confidence``, ``tier`` and ``score`` are
refused as card-level keys with an error pointing at M3.3. AGENTS.md 6 requires confidence
to be *computed* from evidence tier, effect size, replication, allele frequency,
imputation quality and ancestry match. If a card could simply assert ``confidence: high``,
someone eventually would, the calculator would become decorative, and the rarity inversion
that 4.1 calls the most important thing the UI communicates would be silently overridden
by whoever authored the card. Evidence *inputs* are authored here; the *output* is not.

**The genotype map must be exhaustive.** Every genotype constructible from the declared
alleles needs an outcome. A card mapping only ``AA`` and ``GG`` produces nothing at all for
a heterozygote, and :mod:`genetics.ingest.keys` states the governing problem: "no result"
is indistinguishable from "no variant". An author with nothing to say about heterozygotes
has to say *that*, in an outcome, where the reader can see it. This is the card-level form
of the definition-of-done's ban on silently empty sections.

**Citations are structured, not prose.** See :mod:`genetics.engine.citations`.

**A card declares a position *and* an rsID.** Positional keys are primary
(:mod:`genetics.ingest.keys`) because rsIDs are merged and retired, but authors know
variants by rsID. Requiring both is what lets ``cards lint`` (M3.5) cross-check them
against dbSNP: either alone is unverifiable, and a disagreement means one of them is
wrong. This is also why no card ships in this milestone -- writing coordinates from memory
is the invented-data failure AGENTS.md 6 forbids, and the same reason ``qc/build_anchors``
and the fixture ``spike_ins`` hook both shipped empty.

**Indel alleles are refused.** AGENTS.md 4.2: ``I``/``D`` carry no sequence, either state
may be the reference, and a wrong guess reports the opposite genotype rather than failing.
M1.6 already models the escape hatch -- a whitelist entry that refuses to exist without a
source -- and nothing wires it up yet, so accepting an indel card here would be a claim no
code honours.
"""

from __future__ import annotations

import math
import re
import string
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

import yaml

from genetics.engine import sections
from genetics.engine.citations import Citation, CitationError
from genetics.engine.sections import Section, UnknownSectionError
from genetics.ingest.keys import VariantKey
from genetics.ingest.schema import INDEL_ALLELES, NO_CALL_TOKEN, Chrom
from genetics.paths import repo_root

SCHEMA_VERSION: Final[int] = 1
"""Bumped when a change would make an older reader misinterpret a card file. A reader that
does not recognise the version refuses rather than guessing -- the same contract
``manifest.yaml`` uses, and for the same reason: run bundles record the knowledge-pack
version, and a bundle must be re-readable months later or fail clearly (M4.2)."""

_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9][a-z0-9_]*$")
"""Card ids appear in CLI arguments (``genetics card <run> <card-id>``), URLs and run
bundles. Restricting them to lowercase-and-underscore keeps all three trivially safe."""


class CardError(ValueError):
    """Raised for any structural or semantic problem in a card file."""


# ---------------------------------------------------------------------------
# Evidence vocabulary
# ---------------------------------------------------------------------------


class EvidenceTier(StrEnum):
    """Strength of the *source*, authored.

    Deliberately not called "confidence" and deliberately not sharing its vocabulary. The
    computed output of M3.3 runs ``well-established`` to ``likely-artifact``; this runs
    over study designs. Two ladders with one name would be conflated within a week, and the
    conflation would read as though a card could set its own confidence -- which is the one
    thing this schema exists to prevent.

    Ordered strongest to weakest; :attr:`rank` is what M3.3 consumes.
    """

    CLINICAL_GUIDELINE = "clinical_guideline"
    """CPIC, ACMG. A body has reviewed the evidence and issued a recommendation."""

    EXPERT_CURATED = "expert_curated"
    """ClinVar expert-panel review, PharmGKB level 1A. Curated, not merely deposited."""

    FUNCTIONAL = "functional"
    """The mechanism is established experimentally, not only statistically."""

    GWAS = "gwas"
    """Genome-wide significant in a properly powered association study."""

    CANDIDATE_GENE = "candidate_gene"
    """Pre-GWAS candidate-gene literature. Its own tier because it is largely
    non-replicable, and a card resting on it should be visibly weak rather than merely
    old. Not banned -- AGENTS.md 0.1A labels rather than filters -- but it must show."""

    ANECDOTAL = "anecdotal"
    """Case reports, small series, consumer-genomics folklore with a traceable source."""

    @property
    def rank(self) -> int:
        """0 is strongest. An ordinal, not a score -- M3.3 owns the weighting."""
        return _TIER_ORDER.index(self)


_TIER_ORDER: Final[tuple[EvidenceTier, ...]] = (
    EvidenceTier.CLINICAL_GUIDELINE,
    EvidenceTier.EXPERT_CURATED,
    EvidenceTier.FUNCTIONAL,
    EvidenceTier.GWAS,
    EvidenceTier.CANDIDATE_GENE,
    EvidenceTier.ANECDOTAL,
)


class Replication(StrEnum):
    """Whether anyone else has seen it. Orthogonal to :class:`EvidenceTier` on purpose.

    A well-powered GWAS finding that nobody has replicated and a candidate-gene claim
    replicated across four cohorts are different animals, and one field cannot say both.
    """

    META_ANALYSIS = "meta_analysis"
    INDEPENDENT = "independent"
    """Replicated in a cohort independent of the discovery sample."""

    SAME_COHORT = "same_cohort"
    """Re-analysed in the same data. Not replication, and named so it cannot be mistaken
    for it."""

    NONE = "none"
    CONFLICTING = "conflicting"
    """Replication attempted and disagreed. Distinct from NONE, and worse."""


class EffectMeasure(StrEnum):
    """What the effect number *is*. AGENTS.md requires effect size with units."""

    ODDS_RATIO = "odds_ratio"
    HAZARD_RATIO = "hazard_ratio"
    RISK_RATIO = "risk_ratio"
    BETA = "beta"
    MEAN_DIFFERENCE = "mean_difference"
    PERCENT_VARIANCE_EXPLAINED = "percent_variance_explained"
    PENETRANCE = "penetrance"
    PROPORTION = "proportion"

    @property
    def requires_units(self) -> bool:
        """True where the number is meaningless without them.

        A beta of 0.3 is 0.3 *of something*. A ratio is dimensionless, and inventing units
        for it would be noise -- so units are not merely optional for those, they are
        refused, which keeps ``units: ""`` and ``units: "OR"`` out of the corpus.
        """
        return self in {EffectMeasure.BETA, EffectMeasure.MEAN_DIFFERENCE}

    @property
    def is_proportion(self) -> bool:
        return self in {EffectMeasure.PENETRANCE, EffectMeasure.PROPORTION}

    @property
    def is_ratio(self) -> bool:
        return self in {
            EffectMeasure.ODDS_RATIO,
            EffectMeasure.HAZARD_RATIO,
            EffectMeasure.RISK_RATIO,
        }


class Ancestry(StrEnum):
    """Study population, as 1000 Genomes superpopulation codes.

    A controlled vocabulary rather than free text, because M9.5's portability adjustment
    has to *compare* a study's population against the sample's inferred ancestry, and
    "European"/"EUR"/"european"/"White British" cannot be compared. These five codes have
    been stable since 1000G phase 3 and need no reference download to write down.

    Finer labels (the twenty-six 1000G populations, HGDP, SGDP) arrive with M5.3, which is
    where the reference panel is actually chosen; extending this enum is that milestone's
    job. Until then a study is describable at continental granularity, which is the
    granularity portability arguments are usually made at anyway.
    """

    AFR = "AFR"
    AMR = "AMR"
    EAS = "EAS"
    EUR = "EUR"
    SAS = "SAS"
    MULTI = "MULTI"
    """Explicitly multi-ancestry, e.g. a trans-ethnic meta-analysis."""

    UNKNOWN = "UNKNOWN"
    """The source does not say. Recorded rather than guessed -- an unstated population is
    a real and common property of the literature, and M9.5 must be able to see it."""


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TemplateVar:
    """A placeholder a card template may use, and where its value comes from."""

    name: str
    description: str
    milestone: str | None = None
    """Set when the value is not available yet. A template naming it is refused rather
    than rendered blank -- the same rule M2.1 applies to post-processing steps, where a
    declared-but-unimplemented step reports as outstanding instead of as done."""

    @property
    def available(self) -> bool:
        return self.milestone is None


_TEMPLATE_VARS: Final[tuple[TemplateVar, ...]] = (
    TemplateVar("genotype", "The sorted allele pair from the normalized table, e.g. 'AG'."),
    TemplateVar("rsid", "The rsID the card matched, as the export wrote it."),
    TemplateVar("rsid_current", "The rsID after dbSNP merge resolution (M1.7)."),
    TemplateVar("gene", "The card's gene symbol."),
    TemplateVar("chrom", "Chromosome."),
    TemplateVar("pos", "GRCh37 position."),
    TemplateVar("effect_value", "The authored effect size."),
    TemplateVar("effect_units", "Its units, empty for dimensionless measures."),
    TemplateVar("sample_size", "Sample size of the source study."),
    # M3.3 supplies this through ConfidenceResult. The remaining entries are declared but
    # not yet suppliable, so authors see the responsible milestone instead of a bare
    # "unknown placeholder".
    TemplateVar("confidence", "The computed confidence tier."),
    TemplateVar("frequency", "Population allele frequency from gnomAD.", milestone="M7.2"),
    TemplateVar("ppv", "Empirical PPV for the frequency band.", milestone="M7.3"),
    TemplateVar("ancestry", "The sample's inferred ancestry.", milestone="M5.8"),
    TemplateVar("imputation_quality", "Per-variant r2/DR2.", milestone="M8.5"),
    TemplateVar("percentile", "Placement in the reference distribution.", milestone="M9.4"),
)

TEMPLATE_VARS: Final[dict[str, TemplateVar]] = {v.name: v for v in _TEMPLATE_VARS}


_MATCH_VARS: Final[frozenset[str]] = frozenset(
    {
        "genotype",
        "rsid",
        "rsid_current",
        "chrom",
        "pos",
        "effect_value",
        "effect_units",
        "sample_size",
        "confidence",
    }
)
"""Placeholders that need a matched variant and an evidence block behind them. An
impossibility card has neither by construction, so naming one there renders blank."""


def _available_vars(kind: CardKind, *, has_gene: bool) -> frozenset[str]:
    """What *this* card can actually fill in.

    The global registry answers "does this placeholder exist and is the milestone built".
    It cannot answer "can this card supply it", and review found the gap open in both
    directions: an impossibility card accepted ``{genotype}``, which it can never have, and
    any card could name ``{gene}`` without declaring one. Both render blank, which is
    exactly what the milestone gate above exists to prevent -- the same rule, left
    unapplied to the per-card case.
    """
    usable = {name for name, var in TEMPLATE_VARS.items() if var.available}
    if kind is CardKind.IMPOSSIBILITY:
        usable -= _MATCH_VARS
    if not has_gene:
        usable.discard("gene")
    return frozenset(usable)


def _check_template(text: str, where: str, available: frozenset[str] | None = None) -> None:
    """Validate placeholder names, and refuse format specs.

    ``str.format`` syntax rather than Jinja deliberately: knowledge files are data, and a
    template language that can call methods and index attributes is more power than a card
    needs. Restricting to bare ``{name}`` also means the whole check is a parse, with no
    evaluation of anything.
    """
    if not text.strip():
        raise CardError(f"{where}: template is empty")

    try:
        parsed = list(string.Formatter().parse(text))
    except ValueError as exc:
        raise CardError(
            f"{where}: malformed template -- {exc}. A literal brace is written doubled."
        ) from None

    for _literal, name, spec, conversion in parsed:
        if name is None:
            continue
        if name == "":
            raise CardError(f"{where}: positional placeholder {{}} is not allowed; name it")
        if spec or conversion:
            raise CardError(
                f"{where}: placeholder {{{name}}} carries a format spec or conversion. "
                "Card templates are plain named substitutions; format the value in code "
                "where the formatting can be tested."
            )
        var = TEMPLATE_VARS.get(name)
        if var is None:
            usable = ", ".join(sorted(v.name for v in _TEMPLATE_VARS if v.available))
            raise CardError(f"{where}: unknown placeholder {{{name}}}. Available now: {usable}.")
        if not var.available:
            raise CardError(
                f"{where}: placeholder {{{name}}} is supplied by {var.milestone}, which has "
                "not been built. A card that names it would render blank."
            )
        if available is not None and name not in available:
            why = (
                "an impossibility card matches no variant and carries no evidence"
                if name in _MATCH_VARS
                else f"this card declares no {name!r}"
            )
            raise CardError(
                f"{where}: placeholder {{{name}}} cannot be filled by this card -- {why}, "
                "so it would render blank. Available here: "
                f"{', '.join(sorted(available)) or 'none'}."
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require(mapping: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in mapping:
        raise CardError(f"{where}: missing required key {key!r}")
    return mapping[key]


def _reject_unknown(raw: Mapping[str, Any], allowed: Iterable[str], where: str) -> None:
    unexpected = sorted(set(raw) - set(allowed))
    if unexpected:
        raise CardError(
            f"{where}: unexpected key(s) {', '.join(unexpected)}. "
            f"Accepted: {', '.join(sorted(allowed))}."
        )


def _mapping(raw: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise CardError(f"{where}: expected a mapping, got {type(raw).__name__}")
    return raw


def _outcome_name(raw: Any, where: str) -> str:
    """An outcome name, refusing anything YAML did not hand back as a string.

    ``yes`` and ``no`` are the most natural names in the world for a binary trait, and
    unquoted they are **booleans** under YAML 1.1 -- as are ``on``, ``off``, ``true`` and
    ``false``; ``null`` and ``~`` become None, and a bare number becomes an int. Coercing
    with ``str()`` would "work": ``genotypes: {GG: no}`` and ``outcomes: {no: ...}`` both
    become ``"False"`` and match each other, so the card renders with an outcome named
    ``False`` and nobody finds out. Quote one side and not the other and they stop
    matching, with an error blaming an outcome the author can see is right there.

    So the coercion is refused rather than performed, and the message says what to type.
    """
    if isinstance(raw, str):
        name = raw.strip()
        if not name:
            raise CardError(f"{where}: outcome name is empty")
        return name

    if raw is True:
        literal = " -- yes/true/on are YAML 1.1 booleans"
    elif raw is False:
        literal = " -- no/false/off are YAML 1.1 booleans"
    elif raw is None:
        literal = " -- null and ~ are YAML nulls"
    else:
        literal = ""

    raise CardError(
        f"{where}: outcome names must be quoted strings; YAML read this one as "
        f"{type(raw).__name__} {raw!r}{literal}. Put it in quotes."
    )


def _number(raw: Any, where: str, field_name: str) -> float:
    """A YAML scalar that is genuinely a number.

    ``float(raw)`` alone was used for the confidence interval while every other numeric
    field carried an ``isinstance`` guard, and the two failure modes it let through both
    escaped the loader's contract: ``"1.2 (approx)"`` raised an unlocated ``ValueError``
    naming neither the file nor the key, and a list raised ``TypeError`` -- which is not a
    ``ValueError`` at all, so it slipped past every ``except CardError`` in the call chain.
    A malformed card must produce a located :class:`CardError`.
    """
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise CardError(f"{where}: {field_name} must be a number, got {type(raw).__name__}")
    value = float(raw)
    if not math.isfinite(value):
        raise CardError(f"{where}: {field_name} must be finite, got {raw!r}")
    return value


def _string_list(raw: Any, where: str) -> tuple[str, ...]:
    if not isinstance(raw, Sequence) or isinstance(raw, str):
        raise CardError(f"{where}: expected a list of strings")
    out: list[str] = []
    for i, item in enumerate(raw):
        text = str(item).strip()
        if not text:
            raise CardError(f"{where}[{i}]: empty string")
        out.append(text)
    return tuple(out)


# ---------------------------------------------------------------------------
# Effect and evidence
# ---------------------------------------------------------------------------

_EFFECT_KEYS: Final[frozenset[str]] = frozenset(
    {"measure", "value", "units", "ci_low", "ci_high", "context"}
)


@dataclass(frozen=True)
class Effect:
    """An effect size with its units and, where published, its interval."""

    measure: EffectMeasure
    value: float
    units: str | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    context: str | None = None

    @classmethod
    def parse(cls, raw: Any, where: str) -> Effect:
        data = _mapping(raw, where)
        _reject_unknown(data, _EFFECT_KEYS, where)

        measure_text = str(_require(data, "measure", where)).strip().lower()
        try:
            measure = EffectMeasure(measure_text)
        except ValueError:
            known = ", ".join(m.value for m in EffectMeasure)
            raise CardError(f"{where}: unknown measure {measure_text!r}. Known: {known}.") from None

        raw_value = _require(data, "value", where)
        if isinstance(raw_value, bool) or not isinstance(raw_value, int | float):
            raise CardError(f"{where}: value must be a number")
        value = float(raw_value)
        if not math.isfinite(value):
            raise CardError(f"{where}: value must be finite, got {raw_value!r}")

        units = str(data["units"]).strip() if data.get("units") else None
        if measure.requires_units and not units:
            raise CardError(
                f"{where}: {measure.value} needs 'units' -- a bare {value} is not an effect "
                "size, and AGENTS.md requires effect size *with units*."
            )
        if units and not measure.requires_units:
            raise CardError(
                f"{where}: {measure.value} is dimensionless; drop 'units'. Allowing it here "
                "is how 'units: OR' and 'units: \"\"' get into the corpus."
            )

        context = str(data["context"]).strip() if data.get("context") else None
        if measure is EffectMeasure.PROPORTION and not context:
            raise CardError(
                f"{where}: proportion needs 'context' naming its numerator and denominator; "
                "a bare fraction can be mistaken for penetrance"
            )

        if measure.is_proportion and not 0.0 <= value <= 1.0:
            raise CardError(
                f"{where}: {measure.value} must be between 0 and 1, got {value}. "
                "A percentage typed as a proportion is the usual cause."
            )
        if measure.is_ratio and value <= 0:
            raise CardError(f"{where}: {measure.value} must be positive, got {value}")
        if measure is EffectMeasure.PERCENT_VARIANCE_EXPLAINED and not 0.0 <= value <= 100.0:
            raise CardError(
                f"{where}: percent_variance_explained must be between 0 and 100, got {value}"
            )

        low, high = data.get("ci_low"), data.get("ci_high")
        if (low is None) != (high is None):
            raise CardError(f"{where}: give both ci_low and ci_high, or neither")
        if low is not None and high is not None:
            ci_low = _number(low, where, "ci_low")
            ci_high = _number(high, where, "ci_high")
            if ci_low > ci_high:
                raise CardError(f"{where}: ci_low {ci_low} exceeds ci_high {ci_high}")
            if measure.is_ratio and ci_low <= 0:
                raise CardError(f"{where}: {measure.value} interval bounds must be positive")
            if measure.is_proportion and not 0.0 <= ci_low <= ci_high <= 1.0:
                raise CardError(f"{where}: {measure.value} interval must stay between 0 and 1")
            if (
                measure is EffectMeasure.PERCENT_VARIANCE_EXPLAINED
                and not 0.0 <= ci_low <= ci_high <= 100.0
            ):
                raise CardError(
                    f"{where}: percent_variance_explained interval must stay between 0 and 100"
                )
            if not ci_low <= value <= ci_high:
                raise CardError(
                    f"{where}: value {value} lies outside its own interval "
                    f"[{ci_low}, {ci_high}] -- one of the three is transcribed wrong."
                )
            return cls(measure, value, units, ci_low, ci_high, context)

        return cls(measure, value, units, context=context)


_EVIDENCE_KEYS: Final[frozenset[str]] = frozenset(
    {"tier", "effect", "sample_size", "ancestry", "replication", "within_family_attenuation"}
)


@dataclass(frozen=True)
class Evidence:
    """What is known, and how well. All inputs to M3.3; none of them is a confidence."""

    tier: EvidenceTier
    effect: Effect
    sample_size: int
    ancestry: tuple[Ancestry, ...]
    replication: Replication
    within_family_attenuation: float | None = None
    """Fraction of the population effect that survives a within-sibship design, where
    anyone has run one. Population GWAS estimates absorb assortative mating, population
    stratification and indirect parental effects; for education and height the within-family
    estimate is roughly half. M9.6 puts this on the card face when it is known."""

    @classmethod
    def parse(cls, raw: Any, where: str) -> Evidence:
        data = _mapping(raw, where)
        _reject_unknown(data, _EVIDENCE_KEYS, where)

        tier_text = str(_require(data, "tier", where)).strip().lower()
        try:
            tier = EvidenceTier(tier_text)
        except ValueError:
            known = ", ".join(t.value for t in _TIER_ORDER)
            raise CardError(
                f"{where}: unknown evidence tier {tier_text!r}. Known: {known}. "
                "Note this is the strength of the source, not the card's confidence, "
                "which is computed (M3.3)."
            ) from None

        replication_text = str(_require(data, "replication", where)).strip().lower()
        try:
            replication = Replication(replication_text)
        except ValueError:
            known = ", ".join(r.value for r in Replication)
            raise CardError(
                f"{where}: unknown replication status {replication_text!r}. Known: {known}."
            ) from None

        size = _require(data, "sample_size", where)
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            raise CardError(f"{where}: sample_size must be a positive integer")

        ancestry_raw = _string_list(_require(data, "ancestry", where), f"{where}.ancestry")
        if not ancestry_raw:
            raise CardError(
                f"{where}: ancestry must name at least one population. Use UNKNOWN if the "
                "source does not say -- that is a fact about the study, and M9.5 needs it."
            )
        ancestry: list[Ancestry] = []
        for label in ancestry_raw:
            try:
                ancestry.append(Ancestry(label.strip().upper()))
            except ValueError:
                known = ", ".join(a.value for a in Ancestry)
                raise CardError(
                    f"{where}.ancestry: unknown population {label!r}. Known: {known}. "
                    "Finer labels arrive with the reference panel in M5.3."
                ) from None

        attenuation = data.get("within_family_attenuation")
        if attenuation is not None:
            if isinstance(attenuation, bool) or not isinstance(attenuation, int | float):
                raise CardError(f"{where}: within_family_attenuation must be a number")
            attenuation = float(attenuation)
            if not 0.0 < attenuation <= 1.5:
                raise CardError(
                    f"{where}: within_family_attenuation is a fraction of the population "
                    f"effect, so it belongs in (0, 1.5]; got {attenuation}. A percentage "
                    "written as 40 rather than 0.4 is the usual cause."
                )

        return cls(
            tier=tier,
            effect=Effect.parse(_require(data, "effect", where), f"{where}.effect"),
            sample_size=size,
            ancestry=tuple(dict.fromkeys(ancestry)),
            replication=replication,
            within_family_attenuation=attenuation,
        )


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

_VARIANT_KEYS: Final[frozenset[str]] = frozenset({"rsid", "chrom", "pos_grch37", "alleles"})
_RSID_RE: Final[re.Pattern[str]] = re.compile(r"^rs[1-9]\d*$")


@dataclass(frozen=True)
class CardVariant:
    """One variant a card matches on, keyed both ways."""

    rsid: str
    key: VariantKey

    @property
    def genotypes(self) -> tuple[str, ...]:
        """Every genotype string constructible from the declared alleles.

        Always the sorted *pair*: the normalized table writes a haploid call doubled
        (male X, Y, MT), and carries ploidy in ``call_status`` because the genotype string
        cannot -- see :mod:`genetics.ingest.schema`. So there is one genotype vocabulary
        here, not one per chromosome, and a card does not have to know the sample's sex to
        be exhaustive.
        """
        # VariantKey sorts its alleles, so a <= b holds and each pair comes out already in
        # the sorted form the normalized table writes.
        alleles = self.key.alleles
        return tuple(f"{a}{b}" for i, a in enumerate(alleles) for b in alleles[i:])

    @classmethod
    def parse(cls, raw: Any, where: str) -> CardVariant:
        data = _mapping(raw, where)
        _reject_unknown(data, _VARIANT_KEYS, where)

        rsid = str(_require(data, "rsid", where)).strip()
        if not _RSID_RE.fullmatch(rsid):
            raise CardError(f"{where}: rsid must look like 'rs1815739', got {rsid!r}")

        chrom_text = str(_require(data, "chrom", where)).strip().upper()
        try:
            chrom = Chrom(chrom_text)
        except ValueError:
            known = ", ".join(c.value for c in Chrom)
            raise CardError(
                f"{where}: unknown chromosome {chrom_text!r}. Known: {known}. "
                "Vendor codes 23-26 are never valid here."
            ) from None

        pos = _require(data, "pos_grch37", where)
        if isinstance(pos, bool) or not isinstance(pos, int) or pos <= 0:
            raise CardError(f"{where}: pos_grch37 must be a positive integer")

        alleles = _string_list(_require(data, "alleles", where), f"{where}.alleles")
        upper = tuple(a.upper() for a in alleles)
        if len(set(upper)) < 2:
            raise CardError(
                f"{where}.alleles: a variant needs at least two distinct alleles; "
                f"got {list(alleles)}. A monomorphic locus has nothing to interpret."
            )
        for allele in upper:
            if allele in INDEL_ALLELES:
                raise CardError(
                    f"{where}.alleles: indel allele {allele!r} is not matchable "
                    "(AGENTS.md 4.2). The file records no sequence and either state may be "
                    "the reference, so a wrong guess reports the opposite genotype rather "
                    "than failing. M1.6 models the whitelist; nothing wires it up yet."
                )
            if allele == NO_CALL_TOKEN:
                raise CardError(
                    f"{where}.alleles: {NO_CALL_TOKEN!r} is the vendor's no-call token, not "
                    "an allele. Uncalled markers are the engine's business, not a card's."
                )
            if not re.fullmatch(r"[ACGT]", allele):
                raise CardError(f"{where}.alleles: {allele!r} is not a single base A/C/G/T")

        return cls(rsid=rsid, key=VariantKey(chrom, pos, upper))


_MATCH_KEYS: Final[frozenset[str]] = frozenset({"variants", "genotypes"})


@dataclass(frozen=True)
class Match:
    """Which variant, and what each genotype means.

    ``genotypes`` maps a sorted allele pair to an outcome *name*, resolved against the
    card's ``outcomes``. Names rather than inline text because several genotypes usually
    share one interpretation -- a dominant trait says the same thing for ``AA`` and ``AG``
    -- and inlining would duplicate the prose, which is how two copies drift apart.
    """

    variants: tuple[CardVariant, ...]
    genotypes: Mapping[str, str]

    @property
    def variant(self) -> CardVariant:
        """The single variant. Valid because v1 refuses multi-variant cards."""
        return self.variants[0]

    @classmethod
    def parse(cls, raw: Any, where: str) -> Match:
        data = _mapping(raw, where)
        _reject_unknown(data, _MATCH_KEYS, where)

        raw_variants = _require(data, "variants", where)
        if not isinstance(raw_variants, Sequence) or isinstance(raw_variants, str):
            raise CardError(f"{where}.variants: expected a list")
        if not raw_variants:
            raise CardError(f"{where}.variants: a card must match at least one variant")
        if len(raw_variants) > 1:
            raise CardError(
                f"{where}.variants: schema v{SCHEMA_VERSION} matches one variant per card, "
                f"got {len(raw_variants)}. Multi-variant interpretation is haplotype and "
                "diplotype calling, which is M10.1-M10.2's job and needs phase -- a "
                "genotype cross-product would be a different, wrong answer. The field is a "
                "list so the shape survives; the validator refuses what the engine cannot "
                "honour."
            )

        variants = tuple(
            CardVariant.parse(v, f"{where}.variants[{i}]") for i, v in enumerate(raw_variants)
        )

        raw_map = _mapping(_require(data, "genotypes", where), f"{where}.genotypes")
        expected = set(variants[0].genotypes)
        seen: dict[str, str] = {}
        for key, outcome in raw_map.items():
            genotype = "".join(sorted(str(key).strip().upper()))
            if genotype not in expected:
                raise CardError(
                    f"{where}.genotypes: {str(key)!r} is not constructible from alleles "
                    f"{'/'.join(variants[0].key.alleles)}. Expected one of "
                    f"{', '.join(sorted(expected))}."
                )
            if genotype in seen:
                raise CardError(
                    f"{where}.genotypes: {genotype!r} is mapped twice. Genotypes are sorted "
                    "before comparison, so 'AG' and 'GA' are the same key."
                )
            seen[genotype] = _outcome_name(outcome, f"{where}.genotypes.{genotype}")

        missing = sorted(expected - set(seen))
        if missing:
            raise CardError(
                f"{where}.genotypes: no outcome for {', '.join(missing)}. Every genotype "
                "the declared alleles can produce needs one: an unmapped genotype renders "
                "nothing, and a reader cannot tell that from 'the variant was not found'. "
                "If there is genuinely nothing to say, say that in an outcome."
            )

        return cls(variants=variants, genotypes=seen)


# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------


class CardKind(StrEnum):
    INTERPRETATION = "interpretation"
    IMPOSSIBILITY = "impossibility"
    """AGENTS.md 3.2: rendered as an explicit "not determinable" card rather than silently
    omitted, so a reader who has heard of a test elsewhere learns why this tool does not
    do it."""


_OUTCOME_KEYS: Final[frozenset[str]] = frozenset({"summary", "detail"})


@dataclass(frozen=True)
class Outcome:
    """What one group of genotypes means.

    Templates live per outcome rather than per card -- the roadmap sketch put
    ``summary_template``/``detail_template`` on the card, but the interpretation is exactly
    what differs between genotypes, so a card-level template would have to reconstruct it
    through placeholders and lose the ability to say anything genotype-specific.
    """

    summary: str
    detail: str

    @classmethod
    def parse(cls, raw: Any, where: str, available: frozenset[str] | None = None) -> Outcome:
        data = _mapping(raw, where)
        _reject_unknown(data, _OUTCOME_KEYS, where)
        summary = str(_require(data, "summary", where))
        detail = str(_require(data, "detail", where))
        _check_template(summary, f"{where}.summary", available)
        _check_template(detail, f"{where}.detail", available)
        return cls(summary=summary, detail=detail)


_FORBIDDEN_CARD_KEYS: Final[dict[str, str]] = {
    "confidence": "confidence is computed from evidence, frequency and ancestry (M3.3)",
    "tier": "put the source's strength in evidence.tier; the card's tier is computed (M3.3)",
    "score": "scores are computed (M3.3, M9.2)",
    "reliability": "reliability is the computed confidence tier (M3.3)",
}

_CARD_KEYS: Final[frozenset[str]] = frozenset(
    {
        "id",
        "section",
        "kind",
        "title",
        "gene",
        "match",
        "outcomes",
        "evidence",
        "citations",
        "caveats",
        "impossibility_reason",
        "summary",
        "detail",
    }
)


@dataclass(frozen=True)
class Card:
    """One knowledge-pack entry."""

    id: str
    section: Section
    kind: CardKind
    title: str
    citations: tuple[Citation, ...] = ()
    caveats: tuple[str, ...] = ()
    gene: str | None = None

    # Interpretation cards.
    match: Match | None = None
    outcomes: Mapping[str, Outcome] = field(default_factory=dict)
    evidence: Evidence | None = None

    # Impossibility cards.
    impossibility_reason: str | None = None
    summary: str | None = None
    detail: str | None = None

    @property
    def variant_key(self) -> VariantKey | None:
        return self.match.variant.key if self.match else None

    @classmethod
    def parse(cls, raw: Any, where: str) -> Card:
        data = _mapping(raw, where)

        for forbidden, why in _FORBIDDEN_CARD_KEYS.items():
            if forbidden in data:
                raise CardError(
                    f"{where}: a card may not set {forbidden!r} -- {why}. AGENTS.md 6: "
                    "confidence is computed, not authored. Authoring it would let one card "
                    "override the rarity inversion that 4.1 calls the most important thing "
                    "the interface communicates."
                )
        _reject_unknown(data, _CARD_KEYS, where)

        card_id = str(_require(data, "id", where)).strip()
        if not _ID_RE.fullmatch(card_id):
            raise CardError(
                f"{where}: id {card_id!r} must be lowercase letters, digits and underscores "
                "-- it appears in CLI arguments, URLs and run bundles."
            )
        where = f"{where} ({card_id})"

        try:
            section = sections.get(str(_require(data, "section", where))).section
        except UnknownSectionError as exc:
            raise CardError(f"{where}: {exc}") from None

        kind_text = str(_require(data, "kind", where)).strip().lower()
        try:
            kind = CardKind(kind_text)
        except ValueError:
            known = ", ".join(k.value for k in CardKind)
            raise CardError(f"{where}: unknown kind {kind_text!r}. Known: {known}.") from None

        title = str(_require(data, "title", where)).strip()
        if not title:
            raise CardError(f"{where}: title is empty")

        citations = cls._parse_citations(data.get("citations"), where, kind)
        caveats = _string_list(data.get("caveats") or [], f"{where}.caveats")
        gene = str(data["gene"]).strip() if data.get("gene") else None

        if kind is CardKind.IMPOSSIBILITY:
            return cls._parse_impossibility(
                data, where, card_id, section, title, citations, caveats, gene
            )
        return cls._parse_interpretation(
            data, where, card_id, section, title, citations, caveats, gene
        )

    # -- kind-specific -----------------------------------------------------

    @staticmethod
    def _parse_citations(raw: Any, where: str, kind: CardKind) -> tuple[Citation, ...]:
        if raw is None:
            entries: Sequence[Any] = []
        elif isinstance(raw, Sequence) and not isinstance(raw, str):
            entries = raw
        else:
            raise CardError(f"{where}.citations: expected a list")

        try:
            citations = tuple(
                Citation.parse(c, f"{where}.citations[{i}]") for i, c in enumerate(entries)
            )
        except CitationError as exc:
            raise CardError(str(exc)) from None

        if kind is CardKind.INTERPRETATION and not citations:
            raise CardError(
                f"{where}: an interpretation card needs at least one citation. AGENTS.md 3: "
                "a card without a citation does not render."
            )
        return citations

    @classmethod
    def _parse_impossibility(
        cls,
        data: Mapping[str, Any],
        where: str,
        card_id: str,
        section: Section,
        title: str,
        citations: tuple[Citation, ...],
        caveats: tuple[str, ...],
        gene: str | None,
    ) -> Card:
        """An impossibility card explains why something cannot be determined.

        Citations are *not* required here, and that is deliberate rather than an oversight.
        The claim is about the assay -- an array does not measure methylation -- not about
        the person, and demanding a DOI for it pushes an author toward citing something
        tangentially related, which is worse for a reader than citing nothing. The
        substantive requirement is ``impossibility_reason``: the card has to say why.
        """
        for forbidden in ("match", "outcomes", "evidence"):
            if forbidden in data:
                raise CardError(
                    f"{where}: an impossibility card cannot carry {forbidden!r}. It matches "
                    "no genotype by construction -- that is what makes it an impossibility."
                )

        reason = str(_require(data, "impossibility_reason", where)).strip()
        if not reason:
            raise CardError(f"{where}: impossibility_reason is empty")

        summary = str(_require(data, "summary", where))
        detail = str(_require(data, "detail", where))
        # `gene` is carried rather than dropped: AGENTS.md 3.2's own examples are gene-named
        # (SMN1 copy number, RHD, CYP2D6 hybrids), so naming one is legitimate here. It was
        # being parsed and then silently discarded -- a key accepted with no effect, which
        # this module's docstring calls out as indistinguishable from one that was ignored.
        available = _available_vars(CardKind.IMPOSSIBILITY, has_gene=gene is not None)
        _check_template(summary, f"{where}.summary", available)
        _check_template(detail, f"{where}.detail", available)

        return cls(
            id=card_id,
            section=section,
            kind=CardKind.IMPOSSIBILITY,
            title=title,
            citations=citations,
            caveats=caveats,
            gene=gene,
            impossibility_reason=reason,
            summary=summary,
            detail=detail,
        )

    @classmethod
    def _parse_interpretation(
        cls,
        data: Mapping[str, Any],
        where: str,
        card_id: str,
        section: Section,
        title: str,
        citations: tuple[Citation, ...],
        caveats: tuple[str, ...],
        gene: str | None,
    ) -> Card:
        for forbidden in ("impossibility_reason", "summary", "detail"):
            if forbidden in data:
                raise CardError(
                    f"{where}: {forbidden!r} belongs to an impossibility card. An "
                    "interpretation card's text lives per outcome, because that is what "
                    "differs between genotypes."
                )

        match = Match.parse(_require(data, "match", where), f"{where}.match")
        evidence = Evidence.parse(_require(data, "evidence", where), f"{where}.evidence")

        available = _available_vars(CardKind.INTERPRETATION, has_gene=gene is not None)
        raw_outcomes = _mapping(_require(data, "outcomes", where), f"{where}.outcomes")
        outcomes: dict[str, Outcome] = {}
        for raw_name, body in raw_outcomes.items():
            name = _outcome_name(raw_name, f"{where}.outcomes")
            if name in outcomes:
                # Names are stripped so they line up with the genotype map, which means two
                # distinct YAML keys can collapse into one here. A dict comprehension kept
                # the last quietly, so one of the two outcomes -- with its own summary and
                # detail -- would simply never render.
                raise CardError(
                    f"{where}.outcomes: {name!r} is defined twice (names are trimmed, so "
                    f"{raw_name!r} collides with an earlier key). One of the two would be "
                    "silently discarded."
                )
            outcomes[name] = Outcome.parse(body, f"{where}.outcomes.{raw_name}", available)

        referenced = set(match.genotypes.values())
        unknown = sorted(referenced - set(outcomes))
        if unknown:
            raise CardError(
                f"{where}: genotypes map to undefined outcome(s) {', '.join(unknown)}. "
                f"Defined: {', '.join(sorted(outcomes)) or 'none'}."
            )
        unused = sorted(set(outcomes) - referenced)
        if unused:
            raise CardError(
                f"{where}: outcome(s) {', '.join(unused)} are defined but no genotype maps "
                "to them. Usually a renamed outcome or a typo in the genotype map -- either "
                "way some genotype is rendering text nobody intended."
            )

        return cls(
            id=card_id,
            section=section,
            kind=CardKind.INTERPRETATION,
            title=title,
            citations=citations,
            caveats=caveats,
            gene=gene,
            match=match,
            outcomes=outcomes,
            evidence=evidence,
        )


# ---------------------------------------------------------------------------
# The pack
# ---------------------------------------------------------------------------

_FILE_KEYS: Final[frozenset[str]] = frozenset({"schema_version", "cards"})


def parse_file(text: str, where: str) -> tuple[Card, ...]:
    """Parse one knowledge file's contents.

    ``yaml.safe_load`` only, as everywhere else in this project: knowledge files are
    committed data, and ``yaml.load`` would make a data file able to construct objects.
    """
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise CardError(f"{where}: not valid YAML -- {exc}") from None

    if raw is None:
        raise CardError(f"{where}: file is empty")
    data = _mapping(raw, where)
    _reject_unknown(data, _FILE_KEYS, where)

    version = _require(data, "schema_version", where)
    if version != SCHEMA_VERSION:
        raise CardError(
            f"{where}: schema_version {version!r} is not {SCHEMA_VERSION}. A reader that "
            "does not recognise the version refuses rather than guessing at the fields."
        )

    entries = _require(data, "cards", where)
    if not isinstance(entries, Sequence) or isinstance(entries, str):
        raise CardError(f"{where}.cards: expected a list")
    if not entries:
        raise CardError(f"{where}.cards: file declares no cards")

    return tuple(Card.parse(entry, f"{where}.cards[{i}]") for i, entry in enumerate(entries))


@dataclass(frozen=True)
class KnowledgePack:
    """Every card, loaded and validated."""

    cards: tuple[Card, ...]
    source_dir: Path

    def __len__(self) -> int:
        return len(self.cards)

    def by_id(self, card_id: str) -> Card | None:
        return next((c for c in self.cards if c.id == card_id), None)

    def in_section(self, section: Section) -> tuple[Card, ...]:
        return tuple(c for c in self.cards if c.section is section)

    @property
    def empty_sections(self) -> tuple[Section, ...]:
        """Sections with no cards, in render order.

        Surfaced rather than inferred at render time: the definition of done requires every
        section to show either cards or an explicit "nothing determinable here, because X",
        and a caller cannot produce the second without being told which sections need it.
        """
        return tuple(s for s in sections.SECTION_ORDER if not self.in_section(s))

    @classmethod
    def load(cls, directory: Path | None = None) -> KnowledgePack:
        root = directory if directory is not None else default_knowledge_dir()
        if not root.is_dir():
            raise CardError(f"knowledge directory not found: {root}")

        # A card file saved as .yml would be skipped by the glob below and the card would
        # simply not exist -- no error, no card, and "the card is missing" looks exactly
        # like "the card did not match", which is the failure mode this whole schema is
        # organised against. Refuse rather than widen the glob: one extension keeps the
        # duplicate-id check and the lint target unambiguous.
        # Matched case-insensitively on purpose. `rglob("*.yaml")` is case-insensitive on
        # Windows and case-*sensitive* on Linux, so a file committed as `traits.YAML` loads
        # on the author's machine and is silently skipped in CI -- no error, no card, which
        # is the very failure this guard was written for, reintroduced by the guard's own
        # glob.
        strays = sorted(
            p.relative_to(root).as_posix()
            for p in root.rglob("*")
            if p.is_file() and p.suffix.lower() in {".yaml", ".yml"} and p.suffix != ".yaml"
        )
        if strays:
            raise CardError(
                f"{root}: card files must end in a lowercase .yaml, found "
                f"{', '.join(strays)}. Anything else is skipped silently on at least one "
                "platform, and its cards would simply not exist."
            )

        cards: list[Card] = []
        origin: dict[str, Path] = {}
        # Sorted so a duplicate-id error names the same two files on every machine.
        for path in sorted(root.rglob("*.yaml")):
            rel = path.relative_to(root).as_posix()
            for card in parse_file(path.read_text(encoding="utf-8"), rel):
                if card.id in origin:
                    raise CardError(
                        f"duplicate card id {card.id!r} in {rel} and "
                        f"{origin[card.id].relative_to(root).as_posix()}. Ids address cards "
                        "from the CLI and from run bundles, so they have to be unique."
                    )
                origin[card.id] = path
                cards.append(card)

        return cls(cards=tuple(cards), source_dir=root)


def default_knowledge_dir() -> Path:
    """The reviewable checkout corpus, or its installed-wheel copy.

    Committed, unlike references and run bundles: cards are the reviewable corpus, and
    AGENTS.md 3 wants them readable as a diff. Hatch includes the same directory at
    ``genetics/knowledge`` so the installed CLI does not lose its engine data.
    """
    checkout = repo_root() / "knowledge"
    if checkout.is_dir():
        return checkout
    return Path(__file__).resolve().parents[1] / "knowledge"
