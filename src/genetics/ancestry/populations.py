"""Where a sample sits among the reference populations, and when to say nothing (M5.5).

:mod:`genetics.ancestry.projection` produced continuous coordinates. This module turns them
into the thing a card can carry: the reference populations nearest to the sample, how far
away each one is in units that mean something, and -- the requirement the milestone is
really about -- a decision to **name no population at all** when none of them fits.

**Why declining is the load-bearing feature and not a nicety.** With 1000 Genomes alone
there is no Middle Eastern, North African, Oceanian, Central Asian, Siberian or unadmixed
Indigenous American reference population (AGENTS.md 4.6, 5.4). A nearest-neighbour report
over a panel with holes does not return "no match"; it returns the least-bad label with a
number attached, and a number attached is what makes a label read as an answer. Lebanese
comes back as Tuscan. That is not only wrong on the ancestry card: ancestry gates PRS
confidence (AGENTS.md 4.4), so a sample quietly labelled European is a sample whose every
later score is reported as more reliable than it is.

The four decisions below are the ones that make the refusal work.

**1. Distances are measured in units of within-population spread, because the raw ones have
no scale this pipeline is willing to assert.** M5.4 refuses to claim the constant relating
PLINK's ``--score`` averages to the reference's own ``.eigenvec``, and it is right to: the
number would be derived from memory rather than measured. Dividing every axis by the
panel's own *pooled within-population* standard deviation removes the constant entirely --
it cancels, whatever it is. Within-population rather than total: the total spread on an
axis is dominated by the separation between populations, which is the signal being
measured, so dividing by it would shrink precisely the axes that do the separating.

The scaling is diagonal -- one number per component, not a covariance matrix. A full
within-population covariance would be estimated from 61 samples for the smallest 1000
Genomes population, and what it buys over the diagonal is smaller than the noise in that
estimate. It would also put a matrix inversion in the dependency list for a 10x10 problem.

**2. All retained components are used, and the eigenvalues are not a reason to truncate.**
On the real panel the eigenvalues fall 192.6 / 101.6 / 29.4 / 23.3 / 4.6 / 4.1, which reads
as an invitation to keep four and drop the rest as noise. Measured on the real panel,
keeping four breaks the refusal outright. Hold a population out and place its samples:

===========  ==========================  ==========================
Held out     4 components                10 components
===========  ==========================  ==========================
JPT          **0% declined**, named CHB  99% declined
LWK          **0% declined**, named GWD  100% declined
MSL          **0% declined**, named ESN  100% declined
GWD          **0% declined**, named YRI  97% declined
GIH          **0% declined**, named ITU  65% declined
CEU          0% declined, named GBR      0% declined, named GBR
===========  ==========================  ==========================

With four components every population whose substitute does not exist is named anyway, at a
fit near 1 -- which is the Lebanese-as-Tuscan failure reproduced inside the panel. Naming
the *right* population also degrades, from 82.0% of in-panel samples to 69.4%. The small
eigenvalues are small because within-continent structure is a small share of *global*
variance, not because those axes carry nothing, and within-continent is the whole question
here.

**3. Populations are ranked by distance and admitted by fit, and those are two different
numbers on purpose.** ``fit`` is the distance divided by the median distance that
population's own members sit from their own centroid, so ``fit = 1`` is a typical member.
It is the right statistic for *"could this sample be from there"* and the wrong one for
*"what is nearest"*, because a diffuse population has a large radius and therefore attracts
anything unusual: ranked on fit, a held-out Finnish sample's nearest population comes back
as **MXL** -- Mexican ancestry in Los Angeles -- since that admixed cloud is wide enough to
make a huge distance look small. Ranked on distance it comes back as CEU, which is correct.

So the list is ordered by distance and the call is the **closest population that fits**.
Not "the closest one, if it fits": measured on held-out populations, requiring the very
closest to fit refuses 17% of ACB samples, 23% of PJL and 19% of CHS -- each of which has a
perfectly good sibling one step down the list -- while refusing nothing extra where refusing
is the point. FIN, LWK, MSL, JPT, GWD, GIH and every held-out whole region decline
identically under both rules.

**4. The threshold is measured from the panel, not chosen.** ``decline_threshold`` is the
99.5th percentile of the panel's own members' fit to their nearest population, computed at
build time, with a leave-one-out correction so no sample is compared against a centroid it
helped define. It is therefore a sentence rather than a constant: *decline when this sample
sits farther from every reference population than 99.5% of the panel's own members sit from
theirs.* It also moves on its own when the panel widens, which matters because M5.6 adds
AADR and a future SGDP would change the geometry -- a hard-coded number would go on
describing the panel it was tuned against. On the real 1000 Genomes panel it comes out at
2.65; see :data:`DECLINE_QUANTILE` for what that buys and what it costs.

**The region rides with the population call rather than getting a looser rule of its own,
and that was measured too.** Reporting "we cannot name a population, but this is broadly
European" is tempting and is exactly the over-call AGENTS.md 4.4 warns about. The measured
reason it cannot be rescued with a second, looser threshold: a held-out FIN sample -- a
European whose population is genuinely absent -- sits at fit 9.0 from CEU, while held-out
*whole-region* samples with no representation at all reach the nearest population at fit
5.3 (South Asian) and 9.1 (East Asian). Any bar loose enough to keep the Finn as European
admits every one of them, so there is no threshold that separates "a European we have no
population for" from "somebody this panel cannot place". The honest answer is the one the
milestone asked for: name nothing.

**No percentages, and that is the milestone's own preference.** A pie chart implies an
admixture decomposition this module does not compute; what it has are coordinates and
distances, and those are reported as themselves.
"""

from __future__ import annotations

import bisect
import csv
import math
from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Final

import polars as pl

from genetics.ancestry.projection import Projection
from genetics.privacy import NoGenotypeRepr

__all__ = [
    "DECLINE_QUANTILE",
    "HUMAN_ORIGINS_COVERAGE",
    "MIN_POPULATION_SAMPLES",
    "THOUSAND_GENOMES_COVERAGE",
    "CoverageGap",
    "PanelCoverage",
    "Placement",
    "PopulationFit",
    "PopulationLabels",
    "PopulationModel",
    "PopulationsError",
    "build_population_model",
    "coverage_for",
    "place",
    "place_many",
    "read_aadr_population_labels",
    "read_population_labels",
]


DECLINE_QUANTILE: Final = 0.995
"""Where the naming bar sits in the panel's own distribution of nearest-population fits.

The one number in this module that is a choice rather than a measurement, so here is the
measurement it was chosen against. On the real 1000 Genomes panel projected onto a real
AncestryDNA V2.0 marker intersection (2,504 samples, 26 populations, ten components), the
threshold this quantile produces is **2.65**, and:

* **9 of 2,504 panel members are declined by it (0.36%)** -- FIN, LWK, KHV, JPT, GWD and
  CHB samples, which are the panel's own outliers. Of those named, 82.0% get their own
  population and **99.3% get their own region**.
* Hold out a population that has a genuine sibling and the sibling is named: **ACB, BEB,
  CEU, CLM, GBR, IBS, ITU, MXL, PJL, PUR, STU, TSI, YRI 0% declined**; CHS 5%, ESN 5%,
  CDX 6%, ASW 10%.
* Hold out a population with no substitute and it refuses: **FIN 100%, LWK 100%, MSL 100%,
  JPT 99%, GWD 97%, GIH 65%, CHB 63%**.
* Hold out an entire super-population -- the closest thing this panel offers to the
  Oceanian, Central Asian or MENA case -- and it refuses **100% of South Asians, 100% of
  East Asians, 99.7% of Africans, 96.8% of the admixed American samples**. Europeans are
  the weak case at 85.3%, and for an honest reason: held-out Europeans land nearest PUR,
  which genuinely carries substantial European ancestry.

Lowering it to 2.0 would decline 2.5% of genuine panel members and start rejecting
defensible calls (CDX for a held-out KHV, and the reverse); raising it to 3.0 would let two
thirds of held-out CHB samples be named CHS. 0.995 is where the cost stays well under one
percent while the populations that should refuse still do.

**Re-measured against the widened panel (M5.9), and the quantile survived while two things
it implies did not.** On the AADR Human Origins panel -- 5,553 present-day individuals in
100 groups, projected onto the same chip at 44,872 markers -- the same 0.995 produces a
threshold of **2.56** and puts **27 of 5,553 panel members (0.49%)** beyond it, so the cost
side is where it was. What changed:

* **Populations the 1000 Genomes panel had to refuse are now named.** Placing the same
  people against the 26 1000 Genomes populations and then against all 100 -- one space, one
  metric, only the reference set differing -- takes the refusal rate from **32.1% to 0.2%**.
* **The refusal still works where it should.** Held out of the panel entirely, a population
  with no substitute is refused rather than approximated: Nganasan, Kalash, Pima, Mbuti,
  Biaka and Nasioi at 100%, Papuan 98%, Mozabite and Karitiana at 96%, BedouinB 80%. And
  from outside the archive's floor, all 11 Khomani and all 10 Aboriginal Australians.
* **Held out with a sibling present, the sibling is named and it is the right one**:
  Palestinian -> BedouinA and Druze (0% declined), Yemeni_Highlands -> Yemeni_Northwest
  (0%), Iranian -> Iranian_Zoroastrian (3%), Ket -> Selkup (4%), Kazakh -> Uyghur (0%),
  CEU -> GBR (0%), FIN -> Russian (0%), JPT -> Japanese (0%), YRI -> ESN and Yoruba (0%).
* **"Named its own population" stopped being the right measure, and it is the measure that
  fell.** It goes from 82.0% to **68.8%**, because 100 populations include near-siblings the
  26 did not -- Palestinian and Druze and BedouinA, Ket and Selkup, Yakut and Tofalar -- and
  being wrong between those is not the error the old number counted. Measured instead
  against AADR's own sampling coordinates, the 90th-percentile distance between a sample's
  population and the one it was named fell from **3,778 km to 1,212 km**, and the share
  named within 1,000 km rose from 78% to 89%.

The threshold moving from 2.65 to 2.56 is not a tightening: it is a different panel's own
distribution computed the same way, which is the property this quantile has and a
hard-coded number would not.
"""

MIN_POPULATION_SAMPLES: Final = 20
"""Below this a population's radius is an estimate of nothing, so it is left out.

The radius is a median over the population's own members' distances, and the threshold is a
quantile over those. A population contributing five samples would still get a centroid --
and a centroid with a radius fitted to five points is exactly the kind of tight, arbitrary
target that produces a confident population call from nothing.

1000 Genomes' smallest population is ASW at 61, so nothing is dropped there. The number
exists for SGDP, whose public subset averages about two samples per population across 130
of them (AGENTS.md 5.1) -- a panel that would otherwise turn 130 near-singleton clusters
into 130 nameable populations.

**On the widened panel (M5.9) it stops being slack and becomes the binding constraint, and
it binds exactly where the old panel was weakest.** AADR's present-day groups have a median
size in single figures, so this floor takes 2,310 individuals in 520 groups and keeps 5,553
in 100. The ones it takes include the Levant proper: Lebanese_Muslim at 11,
Lebanese_Christian at 9, Jordanian at 12, Egyptian at 18, Assyrian and Armenian at 15,
Moroccan at 10, Tunisian at 8. Those samples are still *placed* -- held out of the panel
entirely they come back as Druze, Palestinian, BedouinA, Georgian and Mozabite rather than
declined -- but they are named a neighbour rather than themselves, and the reason is this
number rather than anything about the archive.

Lowering it would name more of them: 15 admits 133 groups over 6,221 individuals, 10 admits
221 over 7,194. It is not lowered, because :attr:`PopulationModel.own_distances` is a median
over a population's own members and :attr:`PopulationFit.fit` divides by it. A radius fitted
to nine points is a tight, arbitrary target, and a tight target is what turns "we have no
population for this person" into a confident call. The floor stays where the statistic it
feeds can bear it, and what that costs is written down here rather than discovered later.
"""

_MIN_POPULATIONS: Final = 2
"""Fewer than two populations and there is no "nearest" to report, only the only one."""


class PopulationsError(RuntimeError):
    """The reference populations could not be modelled, or a sample could not be placed."""


# ---------------------------------------------------------------------------
# What the panel does not cover
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CoverageGap:
    """A region of the world the reference panel has no population for."""

    region: str
    note: str
    """What a reader of the card deserves to know: not merely that we lack a population,
    but what the nearest thing the panel *would* offer is, so the wrong answer they might
    otherwise have accepted is named."""


@dataclass(frozen=True)
class PanelCoverage:
    """A statement about which parts of the world one specific reference panel covers.

    ``populations`` is the population set the statement is *about*, and it is checked rather
    than assumed. A panel widened by a later milestone -- M5.6's AADR, or SGDP -- would
    otherwise keep this list of gaps attached to it while the gaps had changed, which is
    exactly the failure AGENTS.md 5.2 records for ``refs probe``: a declared fact that
    nothing re-verifies decays quietly and stays green.
    """

    name: str
    populations: frozenset[str]
    gaps: tuple[CoverageGap, ...]


THOUSAND_GENOMES_COVERAGE: Final = PanelCoverage(
    name="1000 Genomes phase 3",
    # The 26 population codes of the phase 3 release. Written out rather than derived from
    # whatever labels arrive, because deriving it would make the check tautological.
    populations=frozenset(
        {
            "ACB",
            "ASW",
            "BEB",
            "CDX",
            "CEU",
            "CHB",
            "CHS",
            "CLM",
            "ESN",
            "FIN",
            "GBR",
            "GIH",
            "GWD",
            "IBS",
            "ITU",
            "JPT",
            "KHV",
            "LWK",
            "MSL",
            "MXL",
            "PEL",
            "PJL",
            "PUR",
            "STU",
            "TSI",
            "YRI",
        }
    ),
    gaps=(
        CoverageGap(
            "Middle East and North Africa",
            "No population from Lebanon, Iran, Turkey, the Arabian peninsula, Egypt or the "
            "Maghreb. Samples from this region fall between the European, South Asian and "
            "African clusters, so the nearest label the panel can offer -- usually Tuscan "
            "or Iberian -- describes a neighbour rather than the sample.",
        ),
        CoverageGap(
            "Oceania",
            "No Papuan, Aboriginal Australian or Melanesian population. Denisovan-related "
            "ancestry, which is a defining feature of this region, has no reference here "
            "at all.",
        ),
        CoverageGap(
            "Central Asia and Siberia",
            "No Kazakh, Uzbek, Mongolian, Turkmen or Siberian population. The panel's "
            "nearest clusters are East Asian and European, and a sample from this region "
            "sits between them without belonging to either.",
        ),
        CoverageGap(
            "Unadmixed Indigenous American",
            "PEL, MXL, CLM and PUR are recent-admixture populations sampled in the "
            "Americas, all carrying substantial European and in places African ancestry. "
            "They are not a reference for Indigenous American ancestry on its own.",
        ),
        CoverageGap(
            "Khoisan and Central African hunter-gatherer",
            "The African populations here are Niger-Congo speaking West and East African, "
            "plus two African-diaspora samples. The deepest-branching human populations -- "
            "Khoisan, Mbuti, Baka -- are absent, and they are the ones a panel this shape "
            "is least able to approximate.",
        ),
    ),
)
"""The gaps AGENTS.md 4.6 and 5.4 record, attached to the panel they are true of.

HGDP covered four of these five and was withdrawn by CEPH for GDPR; SGDP covers them at
about two samples per population, which is breadth in PCA space and useless as a centroid.

**That last sentence used to end "so this is a list of things that stay unanswerable rather
than a to-do", and it was wrong (M5.9, 2026-08-24).** Four of the five are answerable, and
the resource was already on disk: AADR Human Origins carries 8,474 present-day individuals
alongside the ancients M5.6 fetched it for, covering the Middle East, Central Asia, Siberia,
Oceania and unadmixed Indigenous American populations. See
:data:`HUMAN_ORIGINS_COVERAGE` for what the widened panel answers for and what it still
does not. This statement stays attached to the 1000 Genomes population set, which is still
a real panel with these real gaps -- it is the *conclusion* that was wrong, not the list.
"""

HUMAN_ORIGINS_COVERAGE: Final = PanelCoverage(
    name="AADR Human Origins present-day panel",
    # The 100 group labels that reach MIN_POPULATION_SAMPLES in v66.p1_HO. Written out for
    # the reason the 1000 Genomes list is: `coverage_for` matches on this set, and deriving
    # it from whatever the artifact happens to hold would make the match tautological -- a
    # release that dropped a population would silently keep the coverage statement that
    # named the regions it covered.
    populations=frozenset(
        {
            "ACB",
            "ASW",
            "Adygei",
            "Akha",
            "Altaian",
            "BEB",
            "Balochi",
            "Bashkir",
            "Basque",
            "BedouinA",
            "BedouinB",
            "Biaka",
            "Brahui",
            "Burusho",
            "Buryat",
            "CDX",
            "CEU",
            "CHB",
            "CHS",
            "CLM",
            "Chukchi",
            "Dai",
            "Dong",
            "Druze",
            "ESN",
            "English",
            "FIN",
            "Faza_Bajun",
            "French",
            "GBR",
            "GIH",
            "GWD",
            "Georgian",
            "Han",
            "Hazara",
            "Hungarian",
            "IBS",
            "ITU",
            "Iranian",
            "Iranian_Zoroastrian",
            "Italian_North",
            "Italian_South",
            "JPT",
            "Japanese",
            "KHV",
            "Kalash",
            "Karitiana",
            "Kazakh",
            "Ket",
            "Kinh_Vietnamese",
            "LWK",
            "MSL",
            "MXL",
            "Makrani",
            "Mandenka",
            "Mayan",
            "Mbuti",
            "Miao",
            "Mongol",
            "Mordovian",
            "Mozabite",
            "Nasioi",
            "Naxi",
            "Nganasan",
            "Orcadian",
            "Oroqen",
            "PEL",
            "PJL",
            "PUR",
            "Palestinian",
            "Papuan",
            "Pathan",
            "Pima",
            "Punjabi",
            "Qiang",
            "Russian",
            "STU",
            "Sardinian",
            "Selkup",
            "She",
            "Sindhi_Pakistan",
            "Spanish",
            "TSI",
            "Tajik",
            "Tibetan",
            "Tofalar",
            "Tu",
            "Tubalar",
            "Tujia",
            "Turkish",
            "Tuvinian",
            "Ulchi",
            "Uyghur",
            "Uzbek",
            "YRI",
            "Yakut",
            "Yemeni_Highlands",
            "Yemeni_Northwest",
            "Yi",
            "Yoruba",
        }
    ),
    gaps=(
        CoverageGap(
            "The Maghreb east of Algeria, and the Nile valley",
            "Mozabite -- Berber-speaking, from the Algerian M'zab -- is the only North "
            "African population here, and how far it reaches was measured rather than "
            "assumed. It covers the western Maghreb: Algerian (7/7), Berber (5/5) and "
            "Moroccan (8/10) samples are named for it. It does not reach further. Half of "
            "the Tunisians are declined, and Libyan and Egyptian samples come back as "
            "BedouinA -- Arabian, across the Red Sea, a plausible-looking answer for people "
            "whose own populations are in this archive and under the floor.",
        ),
        CoverageGap(
            "Aboriginal Australia",
            "Papuan and Nasioi cover Near Oceania, and Denisovan-related ancestry now has a "
            "reference here where the 1000 Genomes panel had none. Aboriginal Australian "
            "does not: the archive holds 10 individuals, below the floor. All ten are "
            "declined against this panel, which is correct and is also the whole of what "
            "the panel can do for them -- Papuan is the nearest thing it holds, and the "
            "split between those lineages is tens of thousands of years old.",
        ),
        CoverageGap(
            "Khoisan",
            "Mbuti and Biaka close the Central African hunter-gatherer half of what the "
            "1000 Genomes panel lacked. The Khoisan half stays open: Ju_hoan_North (15), "
            "Khomani (11), Khomani_San (2) and Hadza (4) are all under the floor. Khomani "
            "samples are declined, all eleven of them, which is the right answer. "
            "Ju_hoan_North is the one that is not: 10 of 15 come back as Biaka, a Central "
            "African hunter-gatherer population they are about as distant from as any two "
            "human populations are. Biaka's radius is wide enough to admit them, and the "
            "fit statistic has no way to know that the space between them is the deepest "
            "split in human ancestry rather than ordinary distance.",
        ),
        CoverageGap(
            "The Levant, named as itself",
            "Palestinian, Druze, BedouinA and BedouinB place a Levantine sample among "
            "Levantine references, which is what the 1000 Genomes panel could not do at "
            "all. But Lebanese (8 individuals plus 11 Muslim and 9 Christian), Syrian (7) "
            "and Jordanian (12) sit under the floor, so those samples are named a "
            "neighbour rather than their own population: Lebanese_Christian comes back "
            "Druze 9 times out of 9, Jordanian comes back Palestinian 11 times out of 12, "
            "Armenian and Assyrian come back Georgian. Those are good neighbours and they "
            "are not the answer. That is a floor, not an absence: see "
            "MIN_POPULATION_SAMPLES.",
        ),
    ),
)
"""What the widened panel does and does not answer for, measured the same way as the list
above it.

The four regions here are what survives of the five gaps
:data:`THOUSAND_GENOMES_COVERAGE` records. Middle East, Central Asia, Siberia and unadmixed
Indigenous American close outright; Oceania, North Africa and deep-branching Africa close
in part, and the part that stays open is named rather than rounded off. Two of the four are
a floor rather than an archive: the Levant and much of the Maghreb are *present* in AADR and
under :data:`MIN_POPULATION_SAMPLES`, which is a different thing from unobtainable and is
worth a reader knowing, because it moves if the floor ever does.
"""

_KNOWN_PANELS: Final[tuple[PanelCoverage, ...]] = (
    THOUSAND_GENOMES_COVERAGE,
    HUMAN_ORIGINS_COVERAGE,
)


def coverage_for(populations: frozenset[str]) -> PanelCoverage | None:
    """The recorded coverage statement for exactly this population set, or ``None``.

    ``None`` is a meaningful answer and callers must render it as one: it means nobody has
    written down what this panel cannot answer for, **not** that it answers for everything.
    """
    return next((panel for panel in _KNOWN_PANELS if panel.populations == populations), None)


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------


_LABEL_COLUMNS: Final[tuple[str, ...]] = ("sample", "pop", "super_pop")
"""The columns of the 1000 Genomes ``integrated_call_samples`` panel file this reads.

``gender`` is present in that file and deliberately ignored: sex is a property of the
samples, not of the populations, and nothing here groups by it.
"""


@dataclass(frozen=True)
class PopulationLabels:
    """Which population each reference sample belongs to, and which region that is in.

    Carries no genotypes -- a population code is published metadata about a public panel --
    so this is safe to print.
    """

    frame: pl.DataFrame
    """``sample_id``, ``population``, ``region``."""

    source: str
    """The label file's *name*, never its path."""

    @property
    def n_samples(self) -> int:
        return self.frame.height

    @property
    def populations(self) -> frozenset[str]:
        return frozenset(self.frame.get_column("population").unique().to_list())

    @property
    def regions(self) -> Mapping[str, str]:
        """Population to region. One region per population by construction of the panel."""
        pairs = self.frame.select("population", "region").unique().iter_rows()
        return {str(population): str(region) for population, region in pairs}


def read_population_labels(path: Path) -> PopulationLabels:
    """Read a 1000 Genomes sample-panel file as labels.

    Tab-delimited with a header naming ``sample``, ``pop`` and ``super_pop``. The header is
    resolved by name rather than by position, for the reason
    :func:`~genetics.external.harmonize.read_panel_sites` gives about ``.pvar`` columns: the
    published file has a trailing pair of empty column names, so counting fields is a way to
    read the wrong one.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        # `exc` stringifies with its full filename, and a path outside the checkout carries
        # the account name on Windows -- the same reason `PanelSites.source` and friends
        # keep the name and drop the path.
        raise PopulationsError(
            f"could not read the population labels at {path.name}: "
            f"{exc.strerror or exc.__class__.__name__}"
        ) from exc

    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise PopulationsError(f"{path.name} is empty, so no reference sample has a population.")

    header = lines[0].split("\t")
    try:
        indices = tuple(header.index(name) for name in _LABEL_COLUMNS)
    except ValueError as exc:
        raise PopulationsError(
            f"{path.name} names columns {header[:6]}, which is missing one of "
            f"{list(_LABEL_COLUMNS)}; this is not a 1000 Genomes sample panel file."
        ) from exc

    if len(lines) < 2:
        raise PopulationsError(
            f"{path.name} carries a header and no samples, so no reference sample has a "
            "population. A truncated download looks exactly like this."
        )

    rows = [line.split("\t") for line in lines[1:]]
    ragged = next((i for i, row in enumerate(rows) if len(row) <= max(indices)), None)
    if ragged is not None:
        raise PopulationsError(
            f"{path.name} is malformed: data row {ragged + 1} has {len(rows[ragged])} field(s) "
            f"where the columns this reads are at {list(indices)}."
        )

    frame = pl.DataFrame(
        {
            "sample_id": [row[indices[0]].strip() for row in rows],
            "population": [row[indices[1]].strip() for row in rows],
            "region": [row[indices[2]].strip() for row in rows],
        }
    )
    duplicated = frame.height - frame.get_column("sample_id").n_unique()
    if duplicated:
        raise PopulationsError(
            f"{path.name} names {duplicated:,} sample(s) more than once, so a population "
            "centroid would be weighted by whichever rows were repeated."
        )
    return PopulationLabels(frame=frame, source=path.name)


_AADR_LOCALITY_UNKNOWN: Final = ".."
"""What the AADR annotation sheet writes where a field does not apply or is unresolved."""


def read_aadr_population_labels(psam: Path, anno: Path) -> PopulationLabels:
    """Read the modern panel's own ``.psam`` as labels, with regions from the AADR sheet.

    The 1000 Genomes reader above takes a separate published panel file. This one does not
    need to: ``build_modern_reference_panel`` writes each individual's curated group label
    into the family column, so ``--make-pgen`` carries it into the ``.psam`` and the
    population membership travels *with* the genotypes it describes. There is no second file
    to fall out of step with the first, which is the failure mode a sample-panel file has.

    **The region is the sampling locality's country, and it is AADR's own field rather than
    a taxonomy invented here.** 1000 Genomes ships a super-population code (EUR, AFR, EAS,
    SAS, AMR) and AADR ships nothing of the kind, so the choice was between a continental
    grouping written from memory and the ``Political Entity`` the archive records. Writing
    one is the plausible-looking fabrication [AGENTS.md 6](../../AGENTS.md) forbids -- there
    is no agreed answer for where Turkey or the Caucasus or Central Asia belongs, and
    picking one silently would put an editorial judgement inside a data field.

    So a card reading this says "Druze, Israel" where the old panel said "TSI, EUR". That is
    narrower than a region and it is **where these people were sampled, not where their
    population is from**: 45 of the 54 Basques were sampled in France, 6 of 24 Georgians in
    Turkey, 61 of 67 Kazakhs in Kazakhstan and 6 in Russia. The modal country wins, ties
    broken alphabetically so the artifact is reproducible; anything reporting this to a
    reader owes them the distinction.
    """
    try:
        lines = [
            line
            for line in psam.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.strip()
        ]
    except OSError as exc:
        raise PopulationsError(
            f"could not read the panel sample table at {psam.name}: "
            f"{exc.strerror or exc.__class__.__name__}"
        ) from exc

    header = next((line for line in lines if line.startswith("#")), None)
    if header is None:
        raise PopulationsError(
            f"{psam.name} carries no header line, so its columns cannot be located. A .psam "
            "names them on a line beginning with '#'."
        )
    columns = header.lstrip("#").split()
    try:
        fid, iid = columns.index("FID"), columns.index("IID")
    except ValueError as exc:
        raise PopulationsError(
            f"{psam.name} names columns {columns[:6]}, and the modern panel needs FID (the "
            "population) and IID. A .psam written without family IDs has lost the labels, "
            "which are not recoverable from the genotypes."
        ) from exc

    rows = [line.split() for line in lines if not line.startswith("#")]
    if not rows:
        raise PopulationsError(
            f"{psam.name} carries a header and no samples. A truncated build looks exactly "
            "like this."
        )
    ragged = next((i for i, row in enumerate(rows) if len(row) <= max(fid, iid)), None)
    if ragged is not None:
        raise PopulationsError(
            f"{psam.name} is malformed: data row {ragged + 1} has {len(rows[ragged])} "
            f"field(s) where the columns this reads are at {[fid, iid]}."
        )

    wanted = {row[fid] for row in rows}
    regions, n_rows = _modal_localities(anno, wanted)
    unplaced = sorted(wanted - regions.keys())
    if unplaced:
        raise PopulationsError(
            f"{anno.name} records no sampling locality for {len(unplaced)} of the panel's "
            f"{len(wanted)} populations ({', '.join(unplaced[:5])}). Every group in "
            "v66.p1_HO that reaches the panel floor has one, so this is the .psam and the "
            "sheet coming from different releases rather than a gap in the archive; the "
            f"sheet carried {n_rows:,} rows."
        )

    frame = pl.DataFrame(
        {
            "sample_id": [row[iid] for row in rows],
            "population": [row[fid] for row in rows],
            "region": [regions[row[fid]] for row in rows],
        }
    )
    duplicated = frame.height - frame.get_column("sample_id").n_unique()
    if duplicated:
        raise PopulationsError(
            f"{psam.name} names {duplicated:,} sample(s) more than once, so a population "
            "centroid would be weighted by whichever rows were repeated."
        )
    return PopulationLabels(frame=frame, source=psam.name)


def _modal_localities(anno: Path, wanted: AbstractSet[str]) -> tuple[dict[str, str], int]:
    """Each wanted group's most common ``Political Entity``, and the rows scanned.

    Read straight from the sheet rather than through
    :func:`~genetics.ancestry.eigenstrat.read_anno`, which narrows to the four columns M5.6
    needs. Widening that function for one caller would put a column in every reader's way,
    and this is the one place a locality is wanted.

    The row count comes back because the only thing it is for is the caller's error message
    when a group has no locality -- and reading a 15 MB sheet a second time to produce a
    number for an error is the kind of cost that gets paid on the happy path forever.
    """
    counts: dict[str, dict[str, int]] = {}
    n_rows = 0
    try:
        with anno.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            reader = csv.reader(handle, delimiter="\t")
            header = next(reader, None)
            if header is None:
                raise PopulationsError(f"{anno.name} is empty.")
            try:
                group = next(i for i, name in enumerate(header) if "Group ID" in name)
                entity = next(i for i, name in enumerate(header) if "Political Entity" in name)
            except StopIteration:
                raise PopulationsError(
                    f"{anno.name} has no 'Group ID' or 'Political Entity' column, so the "
                    "panel's populations cannot be given a sampling locality."
                ) from None
            for row in reader:
                n_rows += 1
                if len(row) <= max(group, entity) or row[group] not in wanted:
                    continue
                place = row[entity].strip()
                if not place or place == _AADR_LOCALITY_UNKNOWN:
                    continue
                counts.setdefault(row[group], {})
                counts[row[group]][place] = counts[row[group]].get(place, 0) + 1
    except OSError as exc:
        raise PopulationsError(
            f"could not read {anno.name}: {exc.strerror or exc.__class__.__name__}"
        ) from exc
    resolved = {
        name: min(places.items(), key=lambda item: (-item[1], item[0]))[0]
        for name, places in counts.items()
        if places
    }
    return resolved, n_rows


# ---------------------------------------------------------------------------
# The model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PopulationModel:
    """The reference populations in the space M5.4 projects into.

    Built from the *panel's own projection* rather than from PLINK's ``.eigenvec``, which is
    the design M5.4 chose and the reason it takes any pgen: whatever constant relates
    ``--score`` averages to the eigenvectors, it is the same constant on both sides when
    both go through :func:`~genetics.ancestry.projection.project`, so the sample and these
    centroids are comparable by construction rather than by assertion.

    Holds no genotypes: a centroid over sixty-odd public samples is panel metadata, and the
    distances stored per population describe the panel rather than any individual.
    """

    reference: str
    """The reference PCA this was built against, so :func:`place` can refuse a sample
    projected against a different one. See :attr:`~genetics.ancestry.projection.Projection.
    reference`."""

    n_components: int
    scale: tuple[float, ...]
    """Pooled within-population standard deviation per component. Coordinates are divided by
    this before anything else, which is what removes PLINK's unasserted scale constant."""

    centroids: pl.DataFrame
    """``population``, ``region``, ``n``, and ``PC1``..``PCk`` **already scaled**."""

    own_distances: Mapping[str, tuple[float, ...]]
    """Per population, its own members' leave-one-out distances to its centroid, sorted.

    The radius and the percentile on every :class:`PopulationFit` are read off these, so
    they are kept rather than reduced to two summary numbers: a card that says "farther than
    99.8% of Tuscans" is making a claim about a distribution and should be reading one.
    """

    decline_threshold: float
    """The fit beyond which no population is named. See :data:`DECLINE_QUANTILE`."""

    quantile: float
    """The quantile :attr:`decline_threshold` was taken at.

    Stored rather than assumed to be :data:`DECLINE_QUANTILE`, because
    :func:`build_population_model` takes it as an argument and the refusal sentence quotes
    it back to the reader. Reading the module constant there produced a sentence that was
    false for any model built with a different one -- "the bar is 1.00, measured as the
    99.5% point" for a model built at the median.
    """

    n_beyond_threshold: int
    """How many of the panel's own members sit above :attr:`decline_threshold`.

    Says how well-determined the bar is, which a single number cannot. On 1000 Genomes at
    the default quantile it is 11 of 2,504 -- a tail with something in it. On a panel of
    two hundred the same quantile lands on the largest observed fit and this reads **0**,
    meaning the bar is "farther than the single most extreme member we happen to have" and
    is one unusual sample away from moving. Reported rather than guarded against with a
    minimum panel size, because the right size depends on the panel and a refusal here
    would block a legitimate small one outright.
    """

    labels_source: str
    n_panel_samples: int
    dropped_populations: Mapping[str, int]
    """Populations left out for having fewer than :data:`MIN_POPULATION_SAMPLES` members,
    and how many they had. Recorded rather than silently skipped -- a panel that lost half
    its populations to this floor is a fact about the answer."""

    coverage: PanelCoverage | None
    """What this panel cannot answer for, or ``None`` when nobody has written it down for
    this exact population set. ``None`` does not mean "no gaps"; see :func:`coverage_for`."""

    @property
    def populations(self) -> tuple[str, ...]:
        return tuple(self.centroids.get_column("population").to_list())

    @property
    def n_populations(self) -> int:
        return self.centroids.height

    def radius(self, population: str) -> float:
        """The median distance this population's own members sit from its centroid."""
        distances = self.own_distances[population]
        middle = len(distances) // 2
        if len(distances) % 2:
            return distances[middle]
        return (distances[middle - 1] + distances[middle]) / 2

    def percentile(self, population: str, distance: float) -> float:
        """Fraction of ``population``'s own members closer to its centroid than ``distance``.

        1.0 means "farther out than every one of them", which is where an unrepresented
        sample lands and is worth being able to say in those words.
        """
        distances = self.own_distances[population]
        return bisect.bisect_left(distances, distance) / len(distances)


def _check_unique_ids(frame: pl.DataFrame, what: str) -> None:
    """Refuse repeated sample ids, which otherwise lose a person without failing.

    The mirror of the guard :func:`read_population_labels` already applies to the label
    file, and it belongs on this side too: a ``.sscore`` reports ``IID`` alone and PLINK
    permits a repeated IID under distinct FIDs. Two individuals sharing one produce a
    *single* :class:`Placement` whose ``fits`` lists every population twice and whose
    coordinates are whichever row the dict happened to keep -- the other person silently
    gone. On the build side the same repetition pulls a centroid toward the duplicated
    sample and inflates ``n``, shrinking that population's leave-one-out correction.
    """
    repeated = frame.height - frame.get_column("sample_id").n_unique()
    if repeated:
        raise PopulationsError(
            f"{what} names {repeated:,} sample id(s) more than once. A repeated id does not "
            "fail anything downstream; it drops one of the samples and doubles the other's "
            "weight."
        )


def _pc_names(k: int) -> list[str]:
    return [f"PC{i + 1}" for i in range(k)]


def _pooled_within_sd(
    frame: pl.DataFrame, centroids: pl.DataFrame, pcs: Sequence[str]
) -> list[float]:
    """One standard deviation per component, pooled across populations.

    Denominator ``N - g`` rather than ``N``: each population's mean is estimated from its own
    members, so ``g`` degrees of freedom are already spent. It matters little at 2,504
    samples over 26 populations and would matter a great deal on a panel of the size the
    :data:`MIN_POPULATION_SAMPLES` floor exists to guard against.
    """
    joined = frame.join(centroids.select("population", *pcs), on="population", suffix="_c")
    degrees = joined.height - centroids.height
    if degrees < 1:
        raise PopulationsError(
            f"the panel has {joined.height} labelled sample(s) across {centroids.height} "
            "population(s), which leaves no degrees of freedom to estimate a spread from."
        )
    out: list[float] = []
    for name in pcs:
        total = joined.select(((pl.col(name) - pl.col(f"{name}_c")) ** 2).sum()).item()
        sd = math.sqrt(float(total) / degrees)
        # `not sd > 0` rather than `sd <= 0`, because every comparison against NaN is false
        # and NaN is the likeliest form an unscalable axis takes. Written the other way, one
        # NaN coordinate anywhere in the panel makes this scale NaN, then the threshold NaN,
        # then every radius NaN -- and the model builds without an error and refuses 100% of
        # samples forever, reporting "nan standard deviations" on every card.
        if not sd > 0.0:
            raise PopulationsError(
                f"component {name} has no usable within-population variation in this panel "
                f"(computed spread {sd}), so a distance along it cannot be scaled. Either "
                "the projection is constant on that axis -- which means the reference PCA "
                "and the panel disagree -- or it carries a NaN."
            )
        out.append(sd)
    return out


def _distance_expr(pcs: Sequence[str]) -> pl.Expr:
    """Euclidean distance between a row's scaled coordinates and a joined centroid's."""
    squares = [(pl.col(name) - pl.col(f"{name}_c")) ** 2 for name in pcs]
    total = squares[0]
    for term in squares[1:]:
        total = total + term
    return total.sqrt()


def build_population_model(
    panel: Projection,
    labels: PopulationLabels,
    *,
    quantile: float = DECLINE_QUANTILE,
    min_population_samples: int = MIN_POPULATION_SAMPLES,
) -> PopulationModel:
    """Fit centroids, spreads and the naming threshold from the projected reference panel.

    ``panel`` must be the *reference panel itself* pushed through
    :func:`~genetics.ancestry.projection.project` -- see this module's docstring for why
    reading ``.eigenvec`` instead would silently mis-scale everything.

    ``min_population_samples`` is a parameter for the same reason ``min_individuals`` is one
    on :func:`~genetics.ancestry.aadr.build_ancient_model`: the floor is a property of the
    panel being fitted, and a test that wants to assert the arithmetic on a hand-built
    three-member population should not have to manufacture twenty of them to do it.
    """
    if not 0.0 < quantile < 1.0:
        raise PopulationsError(f"quantile must lie strictly between 0 and 1, got {quantile}")

    pcs = _pc_names(panel.n_components)
    coordinates = panel.coordinates
    missing = [name for name in ("sample_id", *pcs) if name not in coordinates.columns]
    if missing:
        raise PopulationsError(
            f"the panel projection is missing {missing}; it carries "
            f"{', '.join(coordinates.columns)}."
        )

    _check_unique_ids(coordinates, "the panel projection")
    frame = coordinates.select("sample_id", *pcs).join(labels.frame, on="sample_id", how="left")
    unlabelled = int(frame.get_column("population").is_null().sum())
    if unlabelled:
        raise PopulationsError(
            f"{unlabelled:,} of the panel's {frame.height:,} projected samples have no "
            f"population in {labels.source}. A centroid built from the rest would be a "
            "centroid of whoever happened to be labelled."
        )

    sizes = frame.group_by("population").len()
    small = {
        str(row["population"]): int(row["len"])
        for row in sizes.filter(pl.col("len") < min_population_samples).iter_rows(named=True)
    }
    frame = frame.filter(~pl.col("population").is_in(list(small)))
    if frame.is_empty():
        raise PopulationsError(
            f"every population in {labels.source} has fewer than {MIN_POPULATION_SAMPLES} "
            "projected samples, so none of them can carry a spread."
        )

    centroids = frame.group_by("population").agg(
        pl.col("region").first(),
        pl.len().alias("n"),
        *[pl.col(name).mean().alias(name) for name in pcs],
    )
    if centroids.height < _MIN_POPULATIONS:
        raise PopulationsError(
            f"{centroids.height} population(s) survive in {labels.source}; at least "
            f"{_MIN_POPULATIONS} are needed before 'nearest' means anything."
        )

    scale = _pooled_within_sd(frame, centroids, pcs)
    scaled = frame.with_columns(
        [(pl.col(name) / value).alias(name) for name, value in zip(pcs, scale, strict=True)]
    )
    centroids = centroids.with_columns(
        [(pl.col(name) / value).alias(name) for name, value in zip(pcs, scale, strict=True)]
    ).sort("population")

    # Leave-one-out, in closed form. A member helped define its own centroid, so its raw
    # distance to it is biased low by exactly the amount that member pulled the mean: with
    # c_-i = (n*c - x_i)/(n-1), the distance ||x_i - c_-i|| is ||x_i - c|| * n/(n-1). No
    # refitting per sample, and no approximation.
    own = (
        scaled.join(centroids.select("population", "n", *pcs), on="population", suffix="_c")
        .with_columns((_distance_expr(pcs) * pl.col("n") / (pl.col("n") - 1)).alias("distance"))
        .select("population", "distance")
    )
    own_distances = {
        str(key[0]): tuple(sorted(float(d) for d in group.get_column("distance")))
        for key, group in own.group_by("population")
    }

    model = PopulationModel(
        reference=panel.reference,
        n_components=panel.n_components,
        scale=tuple(scale),
        centroids=centroids,
        own_distances=own_distances,
        # Provisional: the threshold is a quantile over fits, and a fit needs a radius,
        # which needs the distances above. Replaced below, once those exist, by the only
        # value the rest of this function could have used anyway.
        decline_threshold=math.inf,
        quantile=quantile,
        n_beyond_threshold=0,
        labels_source=labels.source,
        n_panel_samples=frame.height,
        dropped_populations=small,
        # The *surviving* set, not the label file's. A population dropped by the floor is a
        # population this model cannot name, so a gap list keyed to the wider set would stay
        # attached to a panel it is no longer exactly true of -- the quiet decay the
        # identity check in `coverage_for` exists to prevent, reintroduced one line above it.
        coverage=coverage_for(frozenset(centroids.get_column("population").to_list())),
    )

    nearest = _nearest_fits(
        model, scaled.select("sample_id", *pcs, pl.col("population").alias("own"))
    )
    fits = sorted(fit for _sample, fit in nearest)
    index = min(len(fits) - 1, max(0, math.ceil(quantile * len(fits)) - 1))
    threshold = fits[index]

    return PopulationModel(
        reference=model.reference,
        n_components=model.n_components,
        scale=model.scale,
        centroids=model.centroids,
        own_distances=model.own_distances,
        decline_threshold=threshold,
        quantile=model.quantile,
        n_beyond_threshold=sum(1 for value in fits if value > threshold),
        labels_source=model.labels_source,
        n_panel_samples=model.n_panel_samples,
        dropped_populations=model.dropped_populations,
        coverage=model.coverage,
    )


def _nearest_fits(model: PopulationModel, rows: pl.DataFrame) -> list[tuple[str, float]]:
    """``(sample_id, fit to the nearest population by distance)`` for calibration.

    ``rows`` carries an ``own`` column naming each sample's own population, and the
    leave-one-out correction is applied to that population's distance only -- the other
    twenty-five centroids owe this sample nothing, so correcting those too would inflate
    every distance and move the threshold for no reason.
    """
    pcs = _pc_names(model.n_components)
    radii = pl.DataFrame(
        {
            "population": list(model.populations),
            "radius": [model.radius(name) for name in model.populations],
        }
    )
    centroids = model.centroids.select("population", "n", *pcs).join(radii, on="population")
    joined = rows.join(centroids, how="cross", suffix="_c")
    scored = (
        joined.with_columns(_distance_expr(pcs).alias("distance"))
        .with_columns(
            pl.when(pl.col("population") == pl.col("own"))
            .then(pl.col("distance") * pl.col("n") / (pl.col("n") - 1))
            .otherwise(pl.col("distance"))
            .alias("distance")
        )
        .with_columns((pl.col("distance") / pl.col("radius")).alias("fit"))
        .sort("distance")
        .group_by("sample_id", maintain_order=True)
        .first()
    )
    return [(str(row[0]), float(row[1])) for row in scored.select("sample_id", "fit").iter_rows()]


# ---------------------------------------------------------------------------
# Placing a sample
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PopulationFit(NoGenotypeRepr):
    """One reference population, and how far the sample sits from it.

    ``NoGenotypeRepr`` because a ranked list of these is an ancestry inference about a
    person, which AGENTS.md 1.1 names in the same breath as PCA coordinates.

    **The population name is withheld, not shown**, which reads oddly for a class whose
    whole subject is a population until you notice how these are reached:
    :attr:`Placement.fits` is ordered nearest-first and :attr:`Placement.nearest` hands back
    the first of them, so ``repr(placement.nearest)`` printing a name *is* the ancestry
    call, in a log line, having taken one attribute access to get around the withholding
    :class:`Placement` does. The first version of this listed ``population`` and so
    published exactly what the class docstring above says it must not.
    """

    _repr_fields: ClassVar[tuple[str, ...]] = ("n_samples",)

    population: str
    region: str
    n_samples: int
    distance: float
    """In pooled within-population standard deviations. Comparable across populations, which
    raw ``--score`` units are not."""

    radius: float
    """The median distance this population's own members sit from its centroid."""

    percentile: float
    """Fraction of this population's own members closer to its centroid than the sample."""

    @property
    def fit(self) -> float:
        """``distance / radius``. One is a typical member of this population."""
        return self.distance / self.radius if self.radius else math.inf


@dataclass(frozen=True)
class Placement(NoGenotypeRepr):
    """Where one sample sits, what it is called, or why it is called nothing.

    ``_repr_fields`` withholds the coordinates and the call itself and shows only the shape
    of the answer, matching :class:`~genetics.ancestry.projection.Projection` and
    :class:`~genetics.ancestry.haplogroup.HaplogroupCall`: the population name is the field a
    debug log would most want and is the one that states an inference about a person.
    """

    _repr_fields: ClassVar[tuple[str, ...]] = ("n_populations", "named", "coverage")

    sample_id: str
    coordinates: tuple[float, ...]
    fits: tuple[PopulationFit, ...]
    """Every population in the model, nearest first by distance."""

    population: str | None
    """The named population, or ``None`` when the sample sits too far from all of them."""

    declined_because: str
    """Empty exactly when :attr:`population` is set."""

    decline_threshold: float
    coverage: float
    """The projection's marker coverage, carried through for the confidence M5.8 computes.

    Not folded into the decision here. A sparsely-called sample's coordinates are noisier
    rather than biased -- ``no-mean-imputation`` means a missing call contributes nothing
    instead of contributing the mean, so the average is taken over what scored -- and noise
    inflates distances, which makes this module decline more readily on its own. Adjusting
    the threshold by coverage on top of that would be correcting for the same thing twice.
    """

    n_scored_markers: int
    n_reference_markers: int
    panel_coverage: PanelCoverage | None
    labels_source: str
    n_panel_samples: int

    @property
    def region(self) -> str | None:
        """The named population's region, or ``None``. Never named on its own -- see the
        module docstring for the measurement behind that.

        Read off :attr:`call` rather than :attr:`nearest`, because those are not always the
        same population: the naming rule takes the closest population that *fits*, and the
        very closest one may be too tight to admit this sample.
        """
        call = self.call
        return call.region if call is not None else None

    @property
    def call(self) -> PopulationFit | None:
        """The fit that was named, or ``None`` when nothing was."""
        if self.population is None:
            return None
        return next(fit for fit in self.fits if fit.population == self.population)

    @property
    def nearest(self) -> PopulationFit:
        """The closest population by distance, named or not. What the decline sentence
        reports, and what a card leads with either way."""
        return self.fits[0]

    @property
    def n_populations(self) -> int:
        return len(self.fits)

    @property
    def named(self) -> bool:
        return self.population is not None


def place_many(
    model: PopulationModel,
    coordinates: pl.DataFrame,
    *,
    coverage: float = 0.0,
    n_scored_markers: int = 0,
    n_reference_markers: int = 0,
) -> tuple[Placement, ...]:
    """Place every row of ``coordinates``. See :func:`place` for the single-sample entry.

    Exposed because the held-out-population checks that calibrate this module place hundreds
    of samples at once, and a test that had to build a :class:`Projection` per sample would
    be testing the constructor. The three coverage figures describe the projection the
    coordinates came from and default to zero for exactly that use -- a caller placing bare
    coordinates has no marker counts to report, and reporting nothing is better than
    reporting somebody else's.
    """
    pcs = _pc_names(model.n_components)
    missing = [name for name in ("sample_id", *pcs) if name not in coordinates.columns]
    if missing:
        raise PopulationsError(
            f"cannot place: the coordinates are missing {missing}; they carry "
            f"{', '.join(coordinates.columns)}."
        )

    _check_unique_ids(coordinates, "the coordinates")
    raw = {
        str(row[0]): tuple(float(value) for value in row[1:])
        for row in coordinates.select("sample_id", *pcs).iter_rows()
    }
    scaled = coordinates.select(
        "sample_id",
        *[(pl.col(name) / value).alias(name) for name, value in zip(pcs, model.scale, strict=True)],
    )
    centroids = model.centroids.select("population", "region", "n", *pcs)
    scored = (
        scaled.join(centroids, how="cross", suffix="_c")
        .with_columns(_distance_expr(pcs).alias("distance"))
        .sort("distance")
    )

    out: list[Placement] = []
    for key, group in scored.group_by("sample_id", maintain_order=True):
        name = str(key[0])
        fits = tuple(
            PopulationFit(
                population=str(row["population"]),
                region=str(row["region"]),
                n_samples=int(row["n"]),
                distance=float(row["distance"]),
                radius=model.radius(str(row["population"])),
                percentile=model.percentile(str(row["population"]), float(row["distance"])),
            )
            for row in group.iter_rows(named=True)
        )
        nearest = fits[0]
        # Nearest first, and the first one whose fit is within the bar wins -- not "the
        # nearest, if it happens to fit". The two differ only when a closer population is
        # tighter than a slightly farther one, and requiring the closest to fit was
        # measurably the worse rule: it declined 17% of held-out ACB samples, 23% of PJL and
        # 19% of CHS, each of which has a perfectly good sibling in the panel, while
        # refusing nothing extra where refusing is the point (FIN, LWK, MSL, JPT, GWD, GIH
        # and every held-out whole region decline identically under both).
        admissible = next((f for f in fits if f.fit <= model.decline_threshold), None)
        population = admissible.population if admissible is not None else None
        out.append(
            Placement(
                sample_id=name,
                coordinates=raw[name],
                fits=fits,
                population=population,
                declined_because="" if population is not None else _decline_reason(nearest, model),
                decline_threshold=model.decline_threshold,
                coverage=coverage,
                n_scored_markers=n_scored_markers,
                n_reference_markers=n_reference_markers,
                panel_coverage=model.coverage,
                labels_source=model.labels_source,
                n_panel_samples=model.n_panel_samples,
            )
        )
    return tuple(out)


def _decline_reason(nearest: PopulationFit, model: PopulationModel) -> str:
    """The sentence the card renders instead of a population name.

    It names the nearest population and its distance, because withholding those would be a
    different failure: the reader is owed what the panel *did* find and why it was not
    enough. What it does not do is offer the name as an answer with a caveat attached, which
    is how a nearest-neighbour report over an incomplete panel usually reads.
    """
    return (
        f"this sample sits {nearest.distance:.1f} within-population standard deviations from "
        f"the nearest reference population ({nearest.population}, {nearest.region}) -- "
        f"{nearest.fit:.1f} times as far as a typical {nearest.population} sample sits from "
        f"that population's centre, and farther out than {nearest.percentile:.1%} of them. "
        f"No other population in the panel fits either. The bar is "
        f"{model.decline_threshold:.2f}, measured as the {model.quantile:.1%} point of "
        f"this panel's own {model.n_panel_samples:,} members against their nearest "
        "population. No population is named, and no region either."
    )


def place(projection: Projection, model: PopulationModel) -> Placement:
    """Place one projected sample against the reference populations.

    Refuses a projection built against a different reference PCA than the model was, because
    the two would be sets of coordinates in different spaces that plot perfectly well
    together -- the same silent-wrongness the ``--score`` variant-ID join has, one milestone
    earlier.
    """
    if projection.reference != model.reference:
        raise PopulationsError(
            f"the sample was projected against reference PCA {projection.reference!r} and the "
            f"population model was built from {model.reference!r}. Those are different "
            "eigenvector sets, so the coordinates are not comparable. Rebuild whichever is "
            "stale and project both through the same one."
        )
    if projection.n_components != model.n_components:
        raise PopulationsError(
            f"the sample carries {projection.n_components} component(s) and the model "
            f"{model.n_components}."
        )
    if projection.n_samples != 1:
        raise PopulationsError(
            f"place() takes a single sample's projection; this one holds "
            f"{projection.n_samples}. Use place_many() for the panel."
        )
    return place_many(
        model,
        projection.coordinates,
        coverage=projection.coverage,
        n_scored_markers=projection.n_scored_markers,
        n_reference_markers=projection.n_reference_markers,
    )[0]
