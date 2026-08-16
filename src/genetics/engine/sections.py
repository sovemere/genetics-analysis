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
        "Lactase persistence, caffeine, alcohol, iron, folate.",
        "M12",
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
        "About offspring rather than self. Incomplete by construction -- see 3.2.",
        "M11.6",
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
    try:
        section = Section(name)
    except ValueError:
        known = ", ".join(s.value for s in SECTION_ORDER)
        raise UnknownSectionError(
            f"unknown section {name!r}. The thirteen sections are fixed by AGENTS.md 3.1; "
            f"adding one is an owner decision, not a card-authoring one. Known: {known}."
        ) from None
    return SECTIONS[section]
