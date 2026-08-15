"""Declared post-download processing steps (roadmap M2.1's last manifest field).

A source is rarely usable as downloaded. gnomAD arrives as half a terabyte of sites VCF
when what the frequency gate needs is one allele frequency per array position; the
imputation panel needs converting to bref3; PhyloTree ships as a zip.

Steps are **declared in the manifest and resolved here**. Two consequences, both of which
are the point:

* A typo in a step name fails when the manifest loads, not after a 60 GB download. That
  ordering is the whole reason this registry exists rather than a dict lookup at run time.
* A step can be declared before it is implemented. :attr:`Step.implemented` is honest
  about which those are, and the fetcher reports them as pending work rather than raising
  after a long download. Several steps here belong to milestones that have not happened
  yet -- M8 owns bref3 conversion -- and pretending otherwise would either block the
  manifest or produce a crash at the worst possible moment.

**Nothing here runs yet, and every step is marked accordingly.** There is no executor:
``Source.post_process`` is read by manifest validation and by the fetcher's pending-work
report, and by nothing else. Three of these were briefly marked ``implemented=True`` on
the grounds that unzipping is easy -- which made them the only steps the fetcher would
*not* list as outstanding, so ``refs fetch --only phylotree_17`` downloaded a zip, never
unpacked it, and reported the source complete with no work left. A claim of
implementation that no code backs is worse than an honest gap, because the gap at least
shows up in the report. The runner arrives with the first milestone that needs one; until
then ``implemented`` stays False everywhere and every declared step is reported pending.

Where the output lands, and why it is not one directory
-------------------------------------------------------
:attr:`Step.output_is_genotype_derived` marks the steps whose output is keyed to *this
user's* array. Subsetting gnomAD to the positions present in a real export produces a file
whose very row set is a fact about that export. That is genotype-derived under
AGENTS.md 1.1 even though every value in it came from a public database, so those outputs
go to the cache directory -- outside the repository entirely -- rather than to
``data/references/``, which is merely gitignored. The distinction is the difference
between a file git will not commit and a file git cannot see.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class Step:
    """One named transformation a source may declare."""

    name: str
    summary: str
    required_params: tuple[str, ...] = ()
    optional_params: tuple[str, ...] = ()

    implemented: bool = False
    """False means declared but not yet built. The fetcher downloads and verifies, then
    reports the step as outstanding."""

    milestone: str = ""
    """Which milestone owns the implementation. Surfaced in the fetch report so "not
    implemented" comes with a date rather than an apology."""

    output_is_genotype_derived: bool = False
    """See the module docstring. Drives the output directory, not just a warning."""


_STEPS: tuple[Step, ...] = (
    Step(
        name="verify_publisher_md5",
        summary=(
            "Fetch the publisher's own .md5 sidecar and check the payload against it, in "
            "addition to the sha256 pinned in the manifest."
        ),
        required_params=("md5_url",),
        milestone="M2.2",
    ),
    Step(
        name="extract_zip",
        summary="Unpack a zip archive into the source's directory.",
        optional_params=("members",),
        milestone="M2.2",
    ),
    Step(
        name="extract_tar",
        summary="Unpack a tar/tar.gz archive into the source's directory.",
        optional_params=("members",),
        milestone="M2.2",
    ),
    Step(
        name="subset_vcf_to_array_positions",
        summary=(
            "Stream a sites VCF and keep only positions present on the array, plus any "
            "position named by a card. Turns gnomAD from a corpus into a lookup table."
        ),
        required_params=("output",),
        optional_params=("info_fields",),
        milestone="M7.2",
        output_is_genotype_derived=True,
    ),
    Step(
        name="extract_rsid_merge_table",
        summary=(
            "Pull the retired-to-current rsID mapping out of the dbSNP VCF into the "
            "compact form MergeTable loads (M1.7)."
        ),
        required_params=("output",),
        milestone="M2.3",
    ),
    Step(
        name="extract_build_anchors",
        summary=(
            "Select markers with confirmed GRCh37 and GRCh38 coordinates and write the "
            "anchor table that qc/build_anchors.py ships empty (M1.5)."
        ),
        required_params=("output",),
        optional_params=("count",),
        milestone="M2.3",
    ),
    Step(
        name="build_pca_marker_subset",
        summary=(
            "Reduce a reference panel to markers overlapping the array, LD-pruned, for "
            "PCA projection. Legitimate here and forbidden for imputation -- see "
            "Source.no_subset."
        ),
        required_params=("output",),
        milestone="M5.3",
        output_is_genotype_derived=True,
    ),
    Step(
        name="convert_to_bref3",
        summary="Convert an imputation reference panel to Beagle's bref3 format.",
        required_params=("output",),
        milestone="M8.2",
    ),
    Step(
        name="parse_pgs_score_licenses",
        summary=(
            "Read the per-score 'License/Terms of Use' column out of "
            "pgs_all_metadata_scores.csv so score selection can honour it (AGENTS.md 4.8)."
        ),
        required_params=("output",),
        milestone="M9.1",
    ),
)

STEPS: Final[dict[str, Step]] = {step.name: step for step in _STEPS}


class UnknownStepError(ValueError):
    """Raised for a post-processing step the registry does not define."""


def get(name: str) -> Step:
    """Look up a step, or raise :class:`UnknownStepError`."""
    try:
        return STEPS[name]
    except KeyError:
        known = ", ".join(sorted(STEPS))
        raise UnknownStepError(
            f"unknown post-processing step {name!r}. Define it in "
            f"genetics.refs.postprocess first. Known steps: {known}."
        ) from None
