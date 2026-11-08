"""The thirteen sections of AGENTS.md 3.1 (roadmap M3.1).

A closed registry, not free text. The section decides where a card renders, and the
dashboard's nav is built from this list; a card whose ``section`` is a typo would render
nowhere at all, and "the card is missing" is the one failure mode that looks identical to
"the card did not match". The definition-of-done forbids a silently empty section, so the
set of sections cannot be open.

Ordered as AGENTS.md 3.1 lists them, which is also the order the roadmap builds them and
the order the UI should show them in: ancestry first because it feeds PRS confidence
(M5.8), traits early because it is the strongest content in the app and demonstrates the
product (M3.6).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class Section(StrEnum):
    ANCESTRY = "ancestry"
    PHYSICAL_HEALTH = "physical_health"
    MENTAL_HEALTH = "mental_health"
    PSYCHOMETRICS = "psychometrics"
    PHARMACOGENOMICS = "pharmacogenomics"
    TRAITS = "traits"
    NUTRITION = "nutrition"
    SUBSTANCE_USE = "substance_use"
    IMMUNOGENETICS = "immunogenetics"
    REPRODUCTIVE = "reproductive"
    GENOME_STRUCTURE = "genome_structure"
    SLEEP_CIRCADIAN = "sleep_circadian"
    FITNESS = "fitness"


@dataclass(frozen=True)
class RelatedCard:
    """A card another section holds that a reader of this one should be pointed to (M12.1).

    A card renders in exactly one section: a second copy would be a second card with the
    same claim, two confidence results to keep in step, and a count that double-counts.
    Some topics still belong to two sections. HFE iron overload and celiac HLA-DQ are
    nutrition topics, but HFE carries a carrier declaration that only physical health and
    reproductive accept, and an HLA card can only sit in immunogenetics or
    pharmacogenomics. A pointer names such a card without moving or copying it.

    ``label`` is shown only when the run does not hold the card -- a run saved before the
    card existed -- so a reader is told it is absent rather than shown a dead link. A test
    checks that every pointer names a card the pack holds in another section.
    """

    card_id: str
    label: str


@dataclass(frozen=True)
class SectionInfo:
    """Display metadata and the roadmap milestone that fills the section.

    ``milestone`` is carried so ``cards lint`` and the dashboard can say *why* a section
    is empty -- "not built yet, M9.8" reads very differently from "nothing matched", and
    the difference is exactly what the no-silent-empty-sections rule is about.
    """

    section: Section
    title: str
    blurb: str
    milestone: str
    related: tuple[RelatedCard, ...] = ()


_INFO: tuple[SectionInfo, ...] = (
    SectionInfo(
        Section.ANCESTRY,
        "Ancestry",
        "PCA projection, ancient-DNA affinity, and haplogroups.",
        "M5",
    ),
    SectionInfo(
        Section.PHYSICAL_HEALTH,
        "Physical health",
        "ClinVar findings and polygenic scores, gated on population frequency.",
        "M7, M9.7",
    ),
    SectionInfo(
        Section.MENTAL_HEALTH,
        "Mental health",
        "Polygenic scores from releases that exclude 23andMe cohorts.",
        "M9.8",
    ),
    SectionInfo(
        Section.PSYCHOMETRICS,
        "Psychometrics",
        "Cognitive and personality scores. The weakest evidence base in the app.",
        "M9.9",
    ),
    SectionInfo(
        Section.PHARMACOGENOMICS,
        "Pharmacogenomics",
        "Drug metabolism from SNP-tractable star alleles.",
        "M10",
    ),
    SectionInfo(
        Section.TRAITS,
        "Traits, morphology & sensory",
        "Common large-effect variants. The most reliable content in the app.",
        "M3.6",
    ),
    SectionInfo(
        Section.NUTRITION,
        "Nutrition & metabolism",
        "Lactase persistence, caffeine, alcohol metabolism, vitamin B12, vitamin D and "
        "folate. Iron overload and celiac HLA-DQ have cards in their own sections.",
        "M12",
        related=(
            RelatedCard("hfe_c282y_iron_overload", "HFE C282Y and iron overload"),
            RelatedCard("hla_celiac_dq2_dq8", "HLA-DQ2.5 and DQ8 and celiac disease"),
        ),
    ),
    SectionInfo(
        Section.SUBSTANCE_USE,
        "Substance use & behavioural propensity",
        "Distinct from both psychometrics and mental health.",
        "M9.10",
    ),
    SectionInfo(
        Section.IMMUNOGENETICS,
        "Immunogenetics (HLA)",
        "HLA types imputed from MHC-region SNPs.",
        "M11",
    ),
    SectionInfo(
        Section.REPRODUCTIVE,
        "Reproductive & carrier status",
        "Carrier findings, about offspring and incomplete by construction (see 3.2), and "
        "polygenic scores for reproductive timing and sex hormones, about self.",
        "M11",
    ),
    SectionInfo(
        Section.GENOME_STRUCTURE,
        "Genome structure",
        "Runs of homozygosity, archaic introgression, sex chromosomes.",
        "M6",
    ),
    SectionInfo(
        Section.SLEEP_CIRCADIAN,
        "Sleep & circadian",
        "Chronotype, sleep duration, insomnia, narcolepsy.",
        "M9.11",
    ),
    SectionInfo(
        Section.FITNESS,
        "Fitness & physiology",
        "ACTN3, ACE, injury and trainability. Weak evidence, included and flagged.",
        "M9.12",
    ),
)

SECTIONS: Final[dict[Section, SectionInfo]] = {info.section: info for info in _INFO}

SECTION_ORDER: Final[tuple[Section, ...]] = tuple(info.section for info in _INFO)
"""Render order. AGENTS.md 3.1's order, not alphabetical or enum-definition order."""


class UnknownSectionError(ValueError):
    """Raised for a section name absent from :class:`Section`.

    Fatal at card-load time. Accepting an unrecognised section would create a fourteenth
    section that no nav renders, so the card would vanish silently -- indistinguishable
    from a card that simply did not match.
    """


def get(name: str) -> SectionInfo:
    # Normalised like every other enum field the card schema reads (kind, evidence tier,
    # replication, ancestry, effect measure). Leaving this one strict made `section: Traits`
    # an error while `kind: Interpretation` was fine, which is the kind of inconsistency an
    # author discovers one field at a time.
    try:
        section = Section(name.strip().lower())
    except ValueError:
        known = ", ".join(s.value for s in SECTION_ORDER)
        raise UnknownSectionError(
            f"unknown section {name!r}. The thirteen sections are fixed by AGENTS.md 3.1; "
            f"adding one is an owner decision, not a card-authoring one. Known: {known}."
        ) from None
    return SECTIONS[section]
