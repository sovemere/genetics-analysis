"""Known-coordinate anchors for the build sanity check (part of roadmap M1.5).

The idea is simple and strong: pick rsIDs whose GRCh37 *and* GRCh38 coordinates are known,
and look at where the file puts them. A file that places them at their GRCh38 positions is
on build 38 no matter what its header says -- and a mislabelled build is the failure mode
that produces confident cards about entirely the wrong genes.

**The table ships empty, deliberately.** Filling it now would mean writing coordinates
from memory, and a wrong reference coordinate committed to a public repo is exactly the
kind of invented data AGENTS.md section 6 forbids. M2 fetches dbSNP and ClinVar; that is
where verified positions come from, and :data:`ANCHORS` is populated there. This follows
the precedent already set by the ``spike_ins`` hook in the fixture generator, which was
left empty for the same reason.

Until then the mechanism is tested with injected anchors and the real build check rests on
the two layers that need no external data: the header assertion (M1.4) and the
coordinate-bounds check in :mod:`genetics.ingest.normalize`.

The gate below matters even once the table is populated: only anchors marked ``verified``
can trigger a hard build failure. An unverified coordinate can then only ever fail to
match, which reads as "indeterminate" -- a wrong anchor loses information rather than
manufacturing a false alarm.
"""

from __future__ import annotations

from dataclasses import dataclass

from genetics.ingest.schema import Chrom

MIN_ANCHORS_FOR_VERDICT = 2
"""One matching anchor is a coincidence waiting to happen -- two positions can collide
across builds. Two concordant anchors is enough to be a fact about the file."""


@dataclass(frozen=True)
class BuildAnchor:
    """One marker whose coordinates are known on both builds."""

    rsid: str
    chrom: Chrom
    pos_grch37: int
    pos_grch38: int
    gene: str
    source: str | None = None
    """Where the coordinates were taken from -- a dbSNP build, a ClinVar release. Required
    for :attr:`verified` to mean anything."""

    @property
    def verified(self) -> bool:
        """True only when the coordinates came from a fetched reference, not from memory.

        Only verified anchors may fail a run. See the module docstring.
        """
        return self.source is not None


ANCHORS: tuple[BuildAnchor, ...] = ()
"""Populated by M2 from dbSNP. See the module docstring for why it is empty here."""
