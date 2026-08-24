"""The modern reference panel, widened from 1000 Genomes to AADR Human Origins (M5.9).

M5.3 built the modern panel from 1000 Genomes phase 3 alone, because that was what could be
fetched: HGDP was withdrawn by CEPH for GDPR and SGDP's public subset averages two samples
per population. The cost was written down honestly in
:data:`~genetics.ancestry.populations.THOUSAND_GENOMES_COVERAGE` -- no Middle Eastern, North
African, Oceanian, Central Asian, Siberian, unadmixed Indigenous American or Khoisan
population exists in that panel, so M5.5 must **decline** for anyone from those regions.

The resource that closes most of that gap was already on disk. AADR ``v66.p1_HO`` was
fetched for [M5.6](../../phase1_roadmap.md), whose question is ancient, and it carries
**8,474 present-day individuals** alongside the ancients -- the Human Origins panel of
Patterson et al. and Lazaridis et al., the 1000 Genomes samples re-genotyped on the same
array, and high-coverage genomes called at the same sites. This module selects the usable
ones and hands them to :mod:`genetics.refs.postprocess`, which prunes them into the pgen
that :func:`~genetics.ancestry.reference_pca.build_reference_pca` computes eigenvectors
from. No new source is fetched: the four files M5.6 already pins are the input.

**What the widening buys, measured through the shipped path on this chip.** All 5,553 panel
members placed against each reference set in the same 44,872-marker space, changing nothing
but which populations are available to name:

===========================  =========  ==========================  ================
Reference set                Declines   90th-pct geographic error   Within 1,000 km
===========================  =========  ==========================  ================
1000 Genomes only (26 pops)  **32.1%**  3,778 km                    78%
Human Origins (100 pops)     **0.2%**   1,212 km                    89%
===========================  =========  ==========================  ================

Geographic error is the distance between the sample's own population and the one it was
named, over AADR's own sampling coordinates -- used because "did it name the right
population" stops meaning much on a panel this dense (see the last paragraph).

And on the case the roadmap names: 148 Levantine and North African individuals in groups
below the panel floor, so in **neither** reference set. The 1000 Genomes set declines
**every one of them**. The widened set names Lebanese_Christian as Druze (9/9), Armenian as
Georgian (15/15), Jordanian as Palestinian (11/12), Egyptian as BedouinA (17/18), Algerian
and Berber as Mozabite (7/7 and 5/5) -- and still declines half the Tunisians, because the
Maghreb rests on Mozabite alone.

**The refusal survives the widening, which was the thing worth checking.** Held out of the
panel entirely, a population with no substitute is still refused rather than approximated:
Nganasan, Kalash, Pima, Mbuti, Biaka and Nasioi at 100%, Papuan 98%, Mozabite and Karitiana
at 96%, BedouinB 80%. The two populations :data:`~genetics.ancestry.populations.HUMAN_
ORIGINS_COVERAGE` names as still uncovered behave the same way from outside: all 11 Khomani
and all 10 Aboriginal Australians are declined. A wider panel that named everybody would
have traded M5.5's whole point for coverage.

Five things about this resource had to be measured rather than assumed, and each is a way
the selection below would otherwise be wrong.

**1. Present-day is a date, not a suffix, and one individual is dated before the present.**
:attr:`~genetics.ancestry.eigenstrat.AadrIndividual.is_ancient` already knows this: dates run
in years before 1950, so ``Khwit.SG`` -- sampled in the 20th century -- carries **-4**. A
selection written as ``date_bp == 0`` drops him; one written as "not ancient" keeps an
individual whose date the sheet never gave. So this takes ``date_bp is not None and
date_bp <= 0``: dated, and not dated into the past.

**2. Two hundred and forty-four present-day individuals carry no heterozygous call at
all.** Two hundred and thirty-three are data type ``Shotgun`` (not ``Shotgun.diploid``):
pseudo-haploid, one randomly drawn read per site doubled, the same representation the
ancients use. They sit inside groups that are otherwise fine -- ASW, GIH, Karitiana, Tajik,
Uzbek, CHB -- and a pseudo-haploid individual carries about twice the per-site variance of a
diploid one, so admitting a handful of them inflates a population's radius, which is what
:func:`~genetics.ancestry.populations.place` divides by.

Excluded **by counting heterozygous calls, not by reading the data type**, following
:mod:`genetics.ancestry.aadr` -- and here the difference is not hypothetical, because the
count finds eleven the suffix does not (see point 3). The measurement is not close: the
244 sit at exactly **0.0000** and the lowest admitted individual at **0.1496**, against a
floor of :data:`DIPLOID_MIN_HETEROZYGOSITY`.

**3. AADR ships outgroups and reference sequences as present-day individuals.** The eleven
non-``Shotgun`` rows in that zero-heterozygosity group are a chimpanzee (twice, once per
data type), a gorilla (twice), a macaque, a marmoset, an orangutan, the hg19 reference
(twice), a reconstructed human-chimp ancestor, and one 1240k human. They are dated ``0``
like everybody else and their localities read ``..``, which cannot be used as the filter
either -- 760 present-day individuals lack a locality, including all of FIN, CHS, STU, ITU
and ASW. What removes them is the diploidy check and the group floor, twice over and neither
on purpose, so :data:`_NON_HUMAN_LABELS` makes it a stated tripwire instead of a coincidence.

**4. AADR encodes QC verdicts in the group label itself.** ``-QCremove``, ``-o``, ``-oPCA``,
``-oRelative``, ``-oAfrica``, ``-Discovery``, ``Ignore_``: 174 labels over 368 present-day
individuals. Most are small enough that the group-size floor would drop them anyway, and
that is precisely why they cannot be left to it -- **``YRI-oRelative`` holds 29 individuals
and clears a floor of 20**, so a selection trusting the floor gains a "population" whose
defining property is that its members are relatives of one another. A centroid of relatives
is tight and confident and wrong.

**5. The Human Origins design carries no strand-ambiguous sites at all.** Not "few": across
all 579,720 autosomal markers there is **no A/T and no C/G pair**. M5.4's ambiguity
exclusion, which costs 2,314 markers against 1000 Genomes, costs nothing here, and the
strand-flip hazard that :func:`~genetics.external.harmonize.panel_exclusion` exists to avoid
does not arise. Nothing in this module acts on that -- the exclusion still runs, and finding
nothing to exclude is the correct outcome -- but it is why the intersection is larger than
the marker counts alone suggest.

**Group labels are populations, and they are finer than 1000 Genomes' were.** 100 of them
reach :data:`~genetics.ancestry.populations.MIN_POPULATION_SAMPLES` where the old panel had
26, and many are near-siblings: Palestinian and Druze and BedouinA, Ket and Selkup, Yakut
and Tofalar. So the share of panel members named *their own* population falls from 82.0% to
**68.8%** -- and that is not a regression, it is the metric going stale. Being wrong between
Druze and Palestinian is not the error the old number counted. What actually fell is the
distance to the truth: the 90th-percentile geographic error dropped from 3,778 km to
1,212 km over the same people, and the share named within 1,000 km rose from 78% to 89%.
:data:`~genetics.ancestry.populations.HUMAN_ORIGINS_COVERAGE` carries this on the panel
rather than leaving a card to imply the old accuracy.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Final

import polars as pl

from genetics.ancestry.eigenstrat import (
    CODE_MISSING,
    AadrIndividual,
    EigenstratError,
    EigenstratSites,
    PackedGenotypes,
    annotate,
    hasharr,
    open_packed,
    read_anno,
    read_ind,
    read_individuals,
    read_records,
    read_snp,
)

__all__ = [
    "AUTOSOMES_HO",
    "DIPLOID_MIN_HETEROZYGOSITY",
    "HETEROZYGOSITY_MARKERS",
    "ModernPanel",
    "ModernPanelError",
    "PanelIndividual",
    "is_analysis_label",
    "open_panel_genotypes",
    "present_day_individuals",
    "select_modern_panel",
    "write_plink_fileset",
]


AUTOSOMES_HO: Final = frozenset(str(chrom) for chrom in range(1, 23))
"""Chromosome labels the AADR ``.snp`` uses for the autosomes.

Plain ``1``..``22``; the sex chromosomes are ``23`` and ``24``. Named here rather than
matched numerically because the file is text and a numeric comparison would quietly accept
whatever a future release wrote in that column.
"""

HETEROZYGOSITY_MARKERS: Final = 20_000
"""How many markers the diploidy check counts over.

Every autosomal marker would answer the same question at 29 times the cost, and the
question is not close: a diploid individual is heterozygous at roughly a third of these
sites and a pseudo-haploid one at **none of them**, by construction rather than by
tendency. Twenty thousand markers separate 6,600-odd from zero. Taken as an even stride
over the file rather than as a prefix, because a prefix is chromosome 1 and this is a
property of the individual's representation, not of a chromosome.
"""

DIPLOID_MIN_HETEROZYGOSITY: Final = 0.02
"""Below this an individual is treated as pseudo-haploid and left out of the panel.

Two orders of magnitude clear of both sides of the measurement it separates. On the pinned
release the present-day individuals split into 4,504 Human Origins and 3,726 shotgun-diploid
samples at a median heterozygosity of **0.336** and **0.331**, and 239 shotgun samples at
exactly **0.0000** -- there is nothing in between to be careful about. The floor is not zero
because "exactly zero" is a claim about a file rather than about a genome: a pseudo-haploid
individual with one miscalled site would pass a zero test and belong on the other side of
it.
"""

_QC_LABEL_MARKERS: Final = (
    "-QCremove",
    "-Discovery",
    "-oRelative",
    "-oPCA",
    "-oAfrica",
    "-oSubSaharan",
)
"""Substrings AADR appends to a group label to record a QC verdict about its members.

Not an exhaustive taxonomy of the resource's labelling -- it is the set observed in
``v66.p1_HO``'s present-day rows, and :func:`is_analysis_label` also refuses the bare ``-o``
outlier mark and the ``Ignore_`` prefix. A label this misses is a label whose members join a
population they were flagged out of, so the floor is the backstop and this is the part that
catches ``YRI-oRelative``, which the floor does not.
"""

_IGNORE_PREFIX: Final = "Ignore_"

_NON_HUMAN_LABELS: Final = frozenset(
    {
        "Ancestor",
        "Chimp",
        "Chimpanzee",
        "Gorilla",
        "Macaque",
        "Marmoset",
        "Orangutan",
        "hg19ref",
    }
)
"""Group labels in ``v66.p1_HO`` that are not people, checked as a tripwire rather than used
as a filter.

**AADR ships outgroups and reference sequences as present-day individuals.** Ten rows carry
``date_bp`` 0 and are a chimpanzee, a gorilla, a macaque, a marmoset, an orangutan, the hg19
reference and a reconstructed human-chimp ancestor. Two existing guards already remove them
and neither is *about* them: their heterozygosity is zero, so the diploidy check takes them,
and their groups hold one or two members, so the floor takes them again.

The floor is the structural one -- an outgroup cannot join a human population, because it
carries its own label, so the only way in is as a population of its own with twenty
members. That is not a thing this resource has. But "not a thing this resource has" is a
statement about a release, and the cost of it changing is a chimpanzee centroid presented as
a human population, so this is checked explicitly and raises rather than filtering silently.
A label that needs adding here is a release worth looking at by hand.

Not a filter, because a filter would make the same list load-bearing while hiding whether it
was ever exercised. Nothing in the pinned release reaches it.
"""


class ModernPanelError(RuntimeError):
    """The modern reference panel could not be selected or written."""


def is_analysis_label(group: str) -> bool:
    """Whether AADR's own annotation leaves this group usable as a population.

    False for the QC and outlier marks listed on :data:`_QC_LABEL_MARKERS`, for the
    ``Ignore_`` prefix, and for a trailing ``-o`` or ``-o<Something>`` -- the resource's
    shorthand for "outlier, excluded from the analyses this label was curated for". Taking
    the publisher's word here rather than re-deriving outlier status is deliberate: the
    curators had the whole dataset and the publication context, and this pipeline has
    neither.
    """
    if group.startswith(_IGNORE_PREFIX):
        return False
    if any(marker in group for marker in _QC_LABEL_MARKERS):
        return False
    tail = group.rsplit("-", 1)[-1] if "-" in group else ""
    # `-o` alone, and `-oSomething` where the something is capitalised: `-oAfrica` and
    # `-oPCA` are named above, but the mark is productive and new ones appear per release.
    # A lowercase tail like `-oceanic` would be part of a name rather than a mark.
    return not (tail == "o" or (tail[:1] == "o" and tail[1:2].isupper()))


@dataclass(frozen=True)
class PanelIndividual:
    """One present-day individual admitted to the panel.

    Carries no genotypes: an identifier, a curated group label and a sex are published
    metadata about a public archive.
    """

    index: int
    """Row in the ``.ind`` file, which is what locates the record in the packed file."""

    sample_id: str
    sex: str
    group: str
    heterozygosity: float
    """Measured over :data:`HETEROZYGOSITY_MARKERS`, and the reason this individual is in
    the panel rather than excluded as pseudo-haploid. Kept so the provenance sidecar can
    record the minimum admitted rather than merely asserting that a check ran."""


@dataclass(frozen=True)
class ModernPanel:
    """The selected present-day individuals, and what selecting them cost.

    Every count is reported rather than merely applied. A panel that silently dropped a
    third of its candidates and a panel that dropped none look identical from the outside,
    and the difference is exactly what a coverage statement is about.
    """

    individuals: tuple[PanelIndividual, ...]
    sites: EigenstratSites
    """The autosomal marker table the panel is written over."""

    n_present_day: int
    """Individuals dated to the present, before any exclusion."""

    n_flagged_label: int
    """Excluded because AADR's own label marks them. See :func:`is_analysis_label`."""

    n_pseudo_haploid: int
    """Excluded because their measured heterozygosity is below
    :data:`DIPLOID_MIN_HETEROZYGOSITY`."""

    n_small_group: int
    """Excluded because their group did not reach the floor. Not a fault in the individual
    -- a fact about how many of their population the resource holds."""

    min_group: int
    """The floor that was applied, recorded because it is the binding constraint on which
    regions the panel can name and a reader deserves to know which number produced this
    membership."""

    @property
    def n_individuals(self) -> int:
        return len(self.individuals)

    @property
    def groups(self) -> tuple[str, ...]:
        """The admitted population labels, sorted."""
        return tuple(sorted({individual.group for individual in self.individuals}))

    @property
    def n_groups(self) -> int:
        return len(self.groups)

    @property
    def min_heterozygosity(self) -> float:
        """The lowest heterozygosity admitted, for the provenance sidecar.

        Recorded rather than asserted: a sidecar saying the diploidy check ran proves
        nothing, and one saying the least heterozygous member of the panel measured 0.150
        against a floor of 0.020 shows how much room the check had.
        """
        return min((individual.heterozygosity for individual in self.individuals), default=0.0)

    def counts(self) -> Mapping[str, int]:
        """Members per admitted group, sorted by label."""
        out: dict[str, int] = {}
        for individual in self.individuals:
            out[individual.group] = out.get(individual.group, 0) + 1
        return dict(sorted(out.items()))

    def labels(self) -> pl.DataFrame:
        """``sample_id``, ``population`` membership, without an invented region.

        :func:`~genetics.ancestry.populations.read_aadr_population_labels` reconstructs the
        same two columns from the emitted ``.psam`` and adds AADR's sampling locality from
        the annotation sheet before the population model consumes them.
        """
        return pl.DataFrame(
            {
                "sample_id": [individual.sample_id for individual in self.individuals],
                "population": [individual.group for individual in self.individuals],
            }
        )


def present_day_individuals(individuals: Iterable[AadrIndividual]) -> list[AadrIndividual]:
    """Those dated to the present: ``date_bp`` known, and not dated into the past.

    ``<= 0`` rather than ``== 0`` because of ``Khwit.SG``, whose date is **-4 BP** -- a
    20th-century individual, which is what "before 1950" makes negative. ``None`` is
    excluded rather than assumed modern: the sheet not naming an individual is a different
    fact from the sheet dating them to now, and
    :attr:`~genetics.ancestry.eigenstrat.AadrIndividual.date_bp` documents that distinction
    for exactly this reason.
    """
    return [
        individual
        for individual in individuals
        if individual.date_bp is not None and individual.date_bp <= 0
    ]


def _heterozygosity_sites(autosomal: Sequence[int]) -> list[int]:
    """An even stride of :data:`HETEROZYGOSITY_MARKERS` rows across the *autosomal* markers.

    Autosomal specifically, and this is the one place where taking the whole file would have
    been quietly wrong rather than merely wasteful: a male's X is hemizygous, so a stride
    that reached chromosomes 23 and 24 would measure every man in the panel as less
    heterozygous than he is and would do it in proportion to how much of the sample fell on
    the sex chromosomes. The floor is two orders of magnitude clear, so it would not have
    misclassified anybody -- which is exactly why it could have stayed wrong for a long time.
    """
    if len(autosomal) <= HETEROZYGOSITY_MARKERS:
        return list(autosomal)
    stride = len(autosomal) / HETEROZYGOSITY_MARKERS
    return sorted({autosomal[int(index * stride)] for index in range(HETEROZYGOSITY_MARKERS)})


def _measure_heterozygosity(
    packed: PackedGenotypes, individuals: Sequence[AadrIndividual], sites: Sequence[int]
) -> dict[int, float]:
    """Heterozygous share of called markers, per individual, over ``sites``.

    Read one marker at a time rather than through :func:`~genetics.ancestry.eigenstrat.
    read_records`, because twenty thousand markers is where the per-marker path is the
    cheap one and the bulk decode is the machinery that is not worth building twice.
    """
    out: dict[int, float] = {}
    order = [individual.index for individual in individuals]
    for index, codes in read_individuals(packed, order, sites):
        called = sum(1 for code in codes if code != CODE_MISSING)
        if called == 0:
            out[index] = 0.0
            continue
        out[index] = sum(1 for code in codes if code == 1) / called
    return out


def select_modern_panel(
    snp: Path,
    ind: Path,
    geno: Path,
    anno: Path,
    *,
    min_group: int,
) -> ModernPanel:
    """Choose the present-day individuals the modern reference panel is built from.

    Four exclusions, in the order they can be decided: dated to the present, label not
    flagged by the resource, measurably diploid, and belonging to a group that reaches
    ``min_group``. The group floor comes last because the three before it change who is
    counted toward it -- applying it first would keep a group of twenty-two that is really
    nineteen once its flagged and pseudo-haploid members are removed.
    """
    if min_group < 2:
        raise ModernPanelError(
            f"min_group must be at least 2, got {min_group}; a population of one has a "
            "radius of zero, and every sample that came near it would fit perfectly."
        )
    sites = read_snp(snp, wanted=None)
    autosomal = sites.frame.filter(pl.col("chrom").is_in(list(AUTOSOMES_HO)))
    if autosomal.height == 0:
        raise ModernPanelError(
            f"{snp.name} names no autosomal marker (chromosomes {sorted(AUTOSOMES_HO)}). "
            "The panel is built on autosomes alone, so there is nothing here to build from."
        )
    sites = EigenstratSites(
        frame=autosomal, source=sites.source, n_read=sites.n_read, id_hash=sites.id_hash
    )

    individuals = annotate(read_ind(ind), read_anno(anno))
    present = present_day_individuals(individuals)
    if not present:
        raise ModernPanelError(
            f"{anno.name} dates no individual to the present, so there is no modern panel "
            "to build. Every individual is either ancient or undated."
        )

    labelled = [item for item in present if is_analysis_label(item.group)]
    n_flagged = len(present) - len(labelled)

    packed = open_packed(
        geno,
        n_individuals=len(individuals),
        n_sites=sites.n_read,
        individual_id_hash=hasharr(item.sample_id for item in individuals),
        site_id_hash=sites.id_hash,
    )
    het = _measure_heterozygosity(packed, labelled, _heterozygosity_sites(sites.indices))
    diploid = [item for item in labelled if het.get(item.index, 0.0) >= DIPLOID_MIN_HETEROZYGOSITY]
    n_pseudo = len(labelled) - len(diploid)

    sizes: dict[str, int] = {}
    for item in diploid:
        sizes[item.group] = sizes.get(item.group, 0) + 1
    kept = [item for item in diploid if sizes[item.group] >= min_group]
    n_small = len(diploid) - len(kept)
    non_human = sorted({item.group for item in kept} & _NON_HUMAN_LABELS)
    if non_human:
        raise ModernPanelError(
            f"{', '.join(non_human)} reached the group floor and would become reference "
            "population(s). These are AADR's outgroups and reference sequences, which the "
            "resource dates to the present alongside people. Neither the diploidy check nor "
            "the group floor is meant to catch them, and in this release both did; if that "
            "has changed, the selection needs a rule that is actually about species rather "
            "than two that happen to work."
        )
    if not kept:
        raise ModernPanelError(
            f"no group reaches {min_group} present-day, unflagged, diploid individuals. "
            f"{len(present):,} were dated to the present, {n_flagged:,} carried a QC or "
            f"outlier label, {n_pseudo:,} measured as pseudo-haploid, and the largest "
            f"surviving group holds {max(sizes.values(), default=0):,}."
        )

    return ModernPanel(
        individuals=tuple(
            PanelIndividual(
                index=item.index,
                sample_id=item.sample_id,
                sex=item.sex,
                group=item.group,
                heterozygosity=het.get(item.index, 0.0),
            )
            # Sorted by file position: `write_plink_fileset` reads the packed file in this
            # order, and a seek pattern that runs forward through a four-gigabyte file is
            # not the same cost as one that jumps.
            for item in sorted(kept, key=lambda item: item.index)
        ),
        sites=sites,
        n_present_day=len(present),
        n_flagged_label=n_flagged,
        n_pseudo_haploid=n_pseudo,
        n_small_group=n_small,
        min_group=min_group,
    )


# ---------------------------------------------------------------------------
# Writing PLINK's binary fileset
# ---------------------------------------------------------------------------

_BED_MAGIC: Final = bytes((0x6C, 0x1B, 0x01))
"""PLINK 1 binary magic, third byte 1 for variant-major. The layout this writes."""

_PLINK_FROM_EIGENSTRAT: Final = (3, 2, 0, 1)
"""EIGENSTRAT code (copies of the ``.snp`` row's first allele) to PLINK's two-bit code.

EIGENSTRAT counts copies of the **first** allele; PLINK's ``00`` is homozygous for the
first allele in the ``.bim`` row. So with the ``.bim`` written first-allele-first, ``2``
(two copies) becomes ``00``, ``1`` becomes ``10`` (heterozygous), ``0`` becomes ``11``, and
:data:`~genetics.ancestry.eigenstrat.CODE_MISSING` becomes ``01``. Written out as a tuple
rather than computed, because each of the four is a fact about a different format and an
arithmetic expression relating them would look like a derivation of something.
"""

_UNPACK: Final = tuple(
    bytes(((value >> (6 - 2 * slot)) & 3) for value in range(256)) for slot in range(4)
)
"""Four 256-byte translation tables, one per slot within a packed byte.

``_UNPACK[s][b]`` is the EIGENSTRAT code of the marker in slot ``s`` of byte ``b`` -- the
``6 - 2s`` shift :func:`~genetics.ancestry.eigenstrat.read_individuals` applies one marker
at a time, precomputed so a whole record decodes in four ``bytes.translate`` calls instead
of half a million shifts.
"""

_PLINK_SHIFTED: Final = tuple(
    bytes((_PLINK_FROM_EIGENSTRAT[value & 3] << (2 * slot)) for value in range(256))
    for slot in range(4)
)
"""EIGENSTRAT code to PLINK code, pre-shifted into each of the four positions in a byte.

PLINK 1 packs the *first* sample into the low-order bits, so sample ``i`` occupies shift
``2 * (i % 4)``. Combining four samples is then an ``or`` of four byte strings, which is
what :func:`_write_bed` does with one big-integer operation apiece.
"""


def _contiguous_run(indices: Sequence[int]) -> tuple[int, int]:
    """``(start, stop)`` of ``indices``, which must be one unbroken ascending run.

    The decode below turns a whole record into one byte per marker in file order and then
    takes a slice. That is a slice, not a gather, and it is what makes the pass fast enough
    to do in Python at all -- a per-marker gather over 5,553 individuals is three billion
    interpreter steps.

    A sorted ``.snp`` puts the autosomes in one run, and the pinned ``v66.p1_HO`` does:
    rows 1 through 579,720, with the sex chromosomes after. A release that interleaved them
    is refused here rather than handled, because handling it means the slow path and a slow
    path nobody has ever run is not a fallback, it is untested code between an archive and
    a panel.
    """
    if not indices:
        raise ModernPanelError("the panel has no markers to write.")
    start, stop = indices[0], indices[-1] + 1
    if stop - start != len(indices):
        raise ModernPanelError(
            f"the panel's {len(indices):,} markers are not one contiguous run of .snp rows "
            f"({start:,}..{stop - 1:,} spans {stop - start:,}). This reader decodes a whole "
            "record and slices it, which a sorted file allows and an interleaved one does "
            "not. The pinned release is sorted; re-check the .snp if this fires."
        )
    return start, stop


def _decode_record(record: bytes, start: int, stop: int) -> bytes:
    """One packed record to one byte per marker, over the half-open row range ``start:stop``.

    Four ``translate`` calls give the four slots; the strided assignments interleave them
    back into file order. Every step is a C-level bulk operation on ``bytes``, which is the
    whole reason this function exists in this shape.
    """
    unpacked = bytearray(len(record) * 4)
    for slot in range(4):
        unpacked[slot::4] = record.translate(_UNPACK[slot])
    return bytes(unpacked[start:stop])


def _write_bed(
    handle: IO[bytes],
    packed: PackedGenotypes,
    individuals: Sequence[PanelIndividual],
    start: int,
    stop: int,
) -> None:
    """Write the variant-major ``.bed`` body for ``individuals``.

    The transpose is the awkward part: the archive is individual-major and PLINK 1 binary is
    variant-major, so every individual contributes two bits to every one of half a million
    records. Done a marker at a time that is 3.2 billion interpreter steps; done like this
    it is one buffer, four ``translate`` calls per individual and one strided assignment per
    group of four.

    The buffer is ``n_markers * ceil(n_individuals / 4)`` bytes -- about 800 MB for the
    pinned release, held once. [AGENTS.md 0.1C](../../AGENTS.md) puts compute cost outside
    the constraints; this is the one place in the module where that licence is spent, and it
    is spent on the alternative being an hours-long pass rather than a minutes-long one.
    """
    n_markers = stop - start
    row_bytes = (len(individuals) + 3) // 4
    buffer = bytearray(n_markers * row_bytes)

    group: list[bytes] = []
    slot_of_group = 0
    for position, (_, record) in enumerate(
        read_records(packed, [individual.index for individual in individuals])
    ):
        codes = _decode_record(record, start, stop)
        group.append(codes.translate(_PLINK_SHIFTED[position & 3]))
        slot_of_group = position >> 2
        if position & 3 == 3:
            _flush_group(buffer, group, slot_of_group, row_bytes, n_markers)
            group = []
    if group:
        _flush_group(buffer, group, slot_of_group, row_bytes, n_markers)

    handle.write(_BED_MAGIC)
    handle.write(bytes(buffer))


def _flush_group(
    buffer: bytearray,
    group: Sequence[bytes],
    byte_index: int,
    row_bytes: int,
    n_markers: int,
) -> None:
    """Combine up to four pre-shifted individuals and write their shared byte column.

    The four occupy disjoint bit pairs of the same byte, so combining them is a bitwise
    ``or`` -- taken over the whole ``n_markers``-long string at once by reading it as a
    single integer. ``int.from_bytes`` and ``int.to_bytes`` are the only way to get a
    C-speed elementwise ``or`` over ``bytes`` without a third-party array library, and this
    module is not the place to acquire one.
    """
    combined = 0
    for codes in group:
        combined |= int.from_bytes(codes, "big")
    buffer[byte_index::row_bytes] = combined.to_bytes(n_markers, "big")


def write_plink_fileset(
    panel: ModernPanel, packed: PackedGenotypes, prefix: Path
) -> tuple[Path, Path, Path]:
    """Write ``panel`` as a PLINK 1 ``.bed``/``.bim``/``.fam`` trio. Returns the three paths.

    PLINK 1 binary rather than pgen because this is a *writer*, and the binary format is
    three files whose layout is fully specified in a paragraph each. PLINK 2 reads it and
    converts it in the next step of the transform, which is the right division of labour:
    this module owns knowing what the archive means, and PLINK owns everything after.

    The ``.fam`` puts the group label in the family column. That is not decoration --
    ``--make-pgen`` carries it into the ``.psam``, so the pgen the reference PCA is computed
    from names each sample's population without a second file having to be kept in step
    with it.
    """
    bed, bim, fam = (prefix.with_suffix(suffix) for suffix in (".bed", ".bim", ".fam"))
    indices = panel.sites.indices
    start, stop = _contiguous_run(indices)

    rows = panel.sites.frame.select("chrom", "rsid", "pos", "a1", "a2")
    with bim.open("w", encoding="utf-8", newline="\n") as handle:
        for chrom, rsid, pos, first, second in rows.iter_rows():
            # Genetic position 0: the .snp carries centimorgans for some rows and zero for
            # others, and nothing downstream reads it. Writing the file's own value would
            # put a number in the artifact that is present for some markers and absent for
            # others with no way to tell which.
            handle.write(f"{chrom}\t{rsid}\t0\t{pos}\t{first}\t{second}\n")

    with fam.open("w", encoding="utf-8", newline="\n") as handle:
        for individual in panel.individuals:
            sex = {"M": "1", "F": "2"}.get(individual.sex, "0")
            handle.write(f"{individual.group}\t{individual.sample_id}\t0\t0\t{sex}\t-9\n")

    with bed.open("wb") as handle:
        _write_bed(handle, packed, panel.individuals, start, stop)
    return bed, bim, fam


def open_panel_genotypes(panel: ModernPanel, ind: Path, geno: Path) -> PackedGenotypes:
    """Re-open the packed file for :func:`write_plink_fileset`, validated as before.

    Separate from :func:`select_modern_panel` so that the handle a caller writes with is one
    it opened itself against the same ``.ind`` and ``.snp`` -- the hash check in
    :func:`~genetics.ancestry.eigenstrat.open_packed` is the thing standing between two
    same-shaped releases, and passing a handle around would let a caller write a panel
    selected from one file using genotypes from another.
    """
    try:
        individuals = read_ind(ind)
        return open_packed(
            geno,
            n_individuals=len(individuals),
            n_sites=panel.sites.n_read,
            individual_id_hash=hasharr(item.sample_id for item in individuals),
            site_id_hash=panel.sites.id_hash,
        )
    except EigenstratError as exc:
        raise ModernPanelError(str(exc)) from exc
