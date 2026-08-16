"""QC computations (roadmap M1.5).

The consequential function here is :func:`infer_sex`. Everything else is arithmetic; sex
inference decides how the entire X and Y are *read*, because the vendor writes a
hemizygous call as a doubled homozygote and the file itself cannot tell the two apart
(AGENTS.md section 2). Get it wrong and a male X reads as a genome-wide run of
homozygosity, which would land in the autozygosity card in M6.2 as a striking and
completely false finding.

That is why :func:`resolve_ploidy` refuses to guess. An ambiguous inference leaves the sex
chromosomes marked ``CALLED`` and says so in a warning, rather than picking the likelier
answer -- an unresolved locus is visibly unresolved, while a wrongly resolved one is not.
"""

from __future__ import annotations

import polars as pl

from genetics.ingest.indels import is_indel_expr
from genetics.ingest.normalize import GRCH37_LENGTHS
from genetics.ingest.registry import SourceInfo
from genetics.ingest.schema import (
    AUTOSOMES,
    CALL_STATUS_ORDER,
    CallStatus,
    Chrom,
    GenotypeTable,
)
from genetics.qc.build_anchors import ANCHORS, MIN_ANCHORS_FOR_VERDICT, BuildAnchor
from genetics.qc.report import (
    BuildCheck,
    BuildVerdict,
    CallRates,
    ChromCallRate,
    DuplicateSummary,
    Heterozygosity,
    IndelSummary,
    InferredSex,
    QCReport,
    SexInference,
)

# --- thresholds -------------------------------------------------------------
# Wide gaps on purpose. These separate two populations that are far apart in the data --
# a male X het rate is near zero and a female's is a third -- so a threshold anywhere in
# the middle works. Narrow thresholds would only create false precision.

MALE_MAX_X_HET = 0.05
FEMALE_MIN_X_HET = 0.15
MALE_MIN_Y_CALL = 0.30
FEMALE_MAX_Y_CALL = 0.15

MIN_SEX_LOCI = 100
"""Below this many usable X loci the rate is too noisy to split on. The AncestryDNA V2
array carries ~25k X markers, so this only trips on a truncated file or a vendor layout
that barely covers the X."""

MIN_CHROM_LOCI_FOR_WARNING = 100
"""Below this, a per-chromosome call rate is not worth warning about -- PAR carries 36
markers on the V2 array, so one no-call there is a 3% "failure".

Deliberately its own constant despite sharing a value with :data:`MIN_SEX_LOCI`. They
answer different questions, and someone retuning the sex-inference threshold should not
silently change which chromosomes get flagged for call rate."""

LOW_CALL_RATE = 0.98
"""Consumer arrays run well above this. Below it, the sample is worth a second look
before its results are believed."""

HIGH_AUTOSOMAL_HET = 0.40
LOW_AUTOSOMAL_HET = 0.15
"""Outside this band, something is off -- contamination pushes heterozygosity up, and
inbreeding or a failed array pushes it down. Reported, never used to reject: an unusual
het rate is a fact about the sample, and M6 has cards that say so properly."""


def _is_snp() -> pl.Expr:
    """SNP loci only: exclude indels and no-calls.

    Indels are excluded from heterozygosity for the same reason they are excluded from
    allele matching (AGENTS.md 4.2): ``I``/``D`` carry no sequence, and their array
    cluster separation is poorer, so they move the rate for reasons unrelated to the
    sample.
    """
    # Every clause is null-safe explicitly rather than by relying on the AND short-
    # circuiting: `null.is_in([...])` is null, not False, and a null predicate matches
    # nothing. That is fine only for as long as the call_status clause stays first, and
    # an invariant that depends on clause order is one refactor from silently inverting.
    return ~is_indel_expr() & (pl.col("call_status").cast(pl.String) != CallStatus.NO_CALL.value)


def _is_het() -> pl.Expr:
    return pl.col("a1") != pl.col("a2")


def call_rates(table: GenotypeTable) -> CallRates:
    """Overall and per-chromosome call rate."""
    frame = table.frame
    total = frame.height
    no_call = int(
        frame.filter(pl.col("call_status").cast(pl.String) == CallStatus.NO_CALL.value).height
    )
    called = total - no_call

    per_chrom = (
        frame.group_by("chrom")
        .agg(
            pl.len().alias("total"),
            (pl.col("call_status").cast(pl.String) != CallStatus.NO_CALL.value)
            .sum()
            .alias("called"),
        )
        .sort("chrom")
    )

    by_chrom = tuple(
        ChromCallRate(
            chrom=str(row["chrom"]),
            total=int(row["total"]),
            called=int(row["called"]),
            call_rate=_rate(int(row["called"]), int(row["total"])),
        )
        for row in per_chrom.iter_rows(named=True)
    )

    return CallRates(
        total_markers=total,
        called=called,
        no_call=no_call,
        call_rate=_rate(called, total),
        by_chrom=by_chrom,
    )


def _rate(numerator: int, denominator: int) -> float:
    """A rate, or 0.0 when there is nothing to divide by.

    Returning 0.0 rather than raising is safe here only because every caller stores the
    denominator alongside the rate -- a 0.0 with a 0 count reads as "no data", which is
    what it means.
    """
    return round(numerator / denominator, 6) if denominator else 0.0


def heterozygosity(table: GenotypeTable) -> Heterozygosity:
    """Autosomal and non-PAR X heterozygosity, on SNP loci."""
    frame = table.frame

    autosomal = frame.filter(
        pl.col("chrom").cast(pl.String).is_in([c.value for c in AUTOSOMES]) & _is_snp()
    )
    x_nonpar = frame.filter((pl.col("chrom").cast(pl.String) == Chrom.X.value) & _is_snp())

    a_total, a_het = autosomal.height, int(autosomal.filter(_is_het()).height)
    x_total, x_het = x_nonpar.height, int(x_nonpar.filter(_is_het()).height)

    return Heterozygosity(
        autosomal_loci=a_total,
        autosomal_het=a_het,
        autosomal_het_rate=_rate(a_het, a_total),
        x_nonpar_loci=x_total,
        x_nonpar_het=x_het,
        x_nonpar_het_rate=_rate(x_het, x_total),
    )


def infer_sex(table: GenotypeTable, het: Heterozygosity) -> SexInference:
    """Infer chromosomal sex from X heterozygosity and Y call rate.

    Two signals rather than one, because each fails differently and they rarely fail
    together. X heterozygosity is the sharper discriminator but goes quiet on a
    poorly-called X; Y call rate is coarse but robust. Requiring them to *agree* is what
    turns a disagreement into ``AMBIGUOUS`` instead of a coin flip -- and a disagreement
    is exactly what a sex-chromosome aneuploidy looks like, which M6.4 has a card for.

    PAR is excluded from the X rate. The pseudoautosomal regions are diploid in both
    sexes, so folding them in would give every male a nonzero X heterozygosity and blunt
    the one signal that separates the two cleanly.
    """
    frame = table.frame
    y_rows = frame.filter(pl.col("chrom").cast(pl.String) == Chrom.Y.value)
    y_total = y_rows.height
    y_called = int(
        y_rows.filter(pl.col("call_status").cast(pl.String) != CallStatus.NO_CALL.value).height
    )
    y_rate = _rate(y_called, y_total)
    x_rate = het.x_nonpar_het_rate

    notes: list[str] = []

    if het.x_nonpar_loci < MIN_SEX_LOCI:
        notes.append(
            f"only {het.x_nonpar_loci} usable non-PAR X loci "
            f"(need {MIN_SEX_LOCI}); the X signal is too sparse to split on"
        )
        return SexInference(
            InferredSex.AMBIGUOUS, x_rate, het.x_nonpar_loci, y_rate, y_total, tuple(notes)
        )

    looks_male_x = x_rate <= MALE_MAX_X_HET
    looks_female_x = x_rate >= FEMALE_MIN_X_HET

    if y_total == 0:
        # A layout with no Y markers at all. Decide on X alone and say so, rather than
        # letting a structurally absent Y masquerade as an uncalled one.
        notes.append("no Y markers in this layout; inference rests on X heterozygosity alone")
        inferred = (
            InferredSex.MALE
            if looks_male_x
            else InferredSex.FEMALE
            if looks_female_x
            else InferredSex.AMBIGUOUS
        )
        return SexInference(inferred, x_rate, het.x_nonpar_loci, y_rate, y_total, tuple(notes))

    looks_male_y = y_rate >= MALE_MIN_Y_CALL
    looks_female_y = y_rate <= FEMALE_MAX_Y_CALL

    if looks_male_x and looks_male_y:
        inferred = InferredSex.MALE
    elif looks_female_x and looks_female_y:
        inferred = InferredSex.FEMALE
    else:
        inferred = InferredSex.AMBIGUOUS
        notes.append(
            f"X heterozygosity {x_rate:.4f} and Y call rate {y_rate:.4f} do not agree on "
            f"a single answer (male: X<={MALE_MAX_X_HET}, Y>={MALE_MIN_Y_CALL}; "
            f"female: X>={FEMALE_MIN_X_HET}, Y<={FEMALE_MAX_Y_CALL}). Hemizygous handling "
            "is left unresolved rather than guessed."
        )

    return SexInference(inferred, x_rate, het.x_nonpar_loci, y_rate, y_total, tuple(notes))


def _hemizygous_mask(sex: InferredSex) -> pl.Expr:
    """Which rows sit at a single-copy locus, given the inferred sex.

    MT is single-copy in everyone, so it resolves without knowing the sex. X and Y do not,
    and under ``AMBIGUOUS`` they stay unresolved -- see the module docstring.
    """
    mt_only = pl.col("chrom").cast(pl.String) == Chrom.MT.value
    if sex is InferredSex.MALE:
        # PAR is deliberately absent: it is diploid in males too.
        return pl.col("chrom").cast(pl.String).is_in([Chrom.X.value, Chrom.Y.value]) | mt_only
    if sex is InferredSex.FEMALE:
        # A female Y call is unexpected rather than hemizygous; it is counted as a warning
        # in run_qc instead of being given a ploidy it has not earned.
        return mt_only

    # AMBIGUOUS. Same expression as the female branch, different reason, so the two are
    # kept apart: this one is a refusal to resolve rather than a resolution. Merging them
    # would lose that, and the next reader would have to rediscover which case they were
    # looking at.
    return mt_only


def resolve_ploidy(table: GenotypeTable, *, sex: InferredSex) -> GenotypeTable:
    """Rewrite ``call_status`` now that the sex is known.

    This is the step that makes a doubled ``A A`` on the male X readable. Until it runs,
    the status column says only "called", which is true and useless: the point of the
    column is that the genotype string cannot carry ploidy.
    """
    hemizygous = _hemizygous_mask(sex)
    called = pl.col("call_status").cast(pl.String) != CallStatus.NO_CALL.value

    status = (
        pl.when(~called)
        .then(pl.lit(CallStatus.NO_CALL.value))
        .when(hemizygous & _is_het())
        .then(pl.lit(CallStatus.HET_HAPLOID.value))
        .when(hemizygous)
        .then(pl.lit(CallStatus.HEMIZYGOUS.value))
        .otherwise(pl.lit(CallStatus.CALLED.value))
        .cast(pl.Enum(CALL_STATUS_ORDER))
        .alias("call_status")
    )

    return GenotypeTable(table.frame.with_columns(status), vendor=table.vendor)


def indel_summary(table: GenotypeTable) -> IndelSummary:
    return IndelSummary(indel_markers=int(table.frame.filter(is_indel_expr()).height))


def duplicate_summary(table: GenotypeTable) -> DuplicateSummary:
    """Count repeated rsIDs and repeated positions.

    Counted as *excess* rows, not as groups: three probes at one position is two
    duplicates, which is the number that matters when deciding whether it is noise or a
    structural problem with the file.
    """
    frame = table.frame
    rsid_excess = frame.height - frame.select("rsid").n_unique()
    pos_excess = frame.height - frame.select("chrom", "pos_grch37").n_unique()
    return DuplicateSummary(duplicate_rsids=int(rsid_excess), duplicate_positions=int(pos_excess))


def check_build(
    table: GenotypeTable,
    *,
    declared: str,
    anchors: tuple[BuildAnchor, ...] = ANCHORS,
) -> BuildCheck:
    """Corroborate the declared build against the coordinates themselves.

    A header is a claim; coordinates are evidence. The bounds half of the check needs no
    reference data at all -- a position past the end of its chromosome is not a GRCh37
    coordinate -- and already ran during normalization, which is why reaching here means
    it passed.

    The anchor half is stronger but needs verified positions, which arrive in M2. Only
    anchors from a fetched reference can produce ``suspected_38``; see
    :mod:`genetics.qc.build_anchors` for why an unverified coordinate is allowed to lose
    information but never to raise a false alarm.
    """
    frame = table.frame
    usable = tuple(a for a in anchors if a.verified)

    found = 0
    match_37 = 0
    match_38 = 0
    for anchor in usable:
        hit = frame.filter(pl.col("rsid") == anchor.rsid)
        if hit.height == 0:
            continue
        found += 1
        positions = set(hit.get_column("pos_grch37").to_list())
        if anchor.pos_grch37 in positions:
            match_37 += 1
        elif anchor.pos_grch38 in positions:
            match_38 += 1

    verdict: BuildVerdict = "indeterminate"
    if match_37 >= MIN_ANCHORS_FOR_VERDICT and match_37 > match_38:
        verdict = "confirmed_37"
    elif match_38 >= MIN_ANCHORS_FOR_VERDICT and match_38 > match_37:
        verdict = "suspected_38"

    return BuildCheck(
        declared=declared,
        # Normalization rejects out-of-range coordinates outright, so a table that exists
        # has already passed. Recorded rather than recomputed, so the report says which
        # checks ran rather than implying one did not.
        coordinates_within_grch37=True,
        anchors_available=len(usable),
        anchors_found=found,
        anchors_matching_37=match_37,
        anchors_matching_38=match_38,
        verdict=verdict,
    )


def _count_het_haploid(table: GenotypeTable, sex: InferredSex) -> int:
    return int(table.frame.filter(_hemizygous_mask(sex) & _is_snp() & _is_het()).height)


def _warnings(
    rates: CallRates,
    het: Heterozygosity,
    sex: SexInference,
    build: BuildCheck,
    duplicates: DuplicateSummary,
    het_haploid: int,
    table: GenotypeTable,
    representable_chroms: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Assemble warnings, most consequential first.

    Warnings label; they never filter (AGENTS.md 0.1A). Nothing in this list causes a row
    to be dropped or a section to be hidden -- the reader is told, and the data stays.
    """
    out: list[str] = []

    if build.verdict == "suspected_38":
        out.append(
            f"coordinates match GRCh38 at {build.anchors_matching_38} verified anchor(s) "
            f"despite a header declaring build {build.declared}. Every downstream lookup "
            "would target the wrong locus."
        )

    if sex.inferred is InferredSex.AMBIGUOUS:
        out.append(
            "chromosomal sex could not be inferred, so X and Y calls are left with "
            "ploidy unresolved. Do not read zygosity off a sex-chromosome call in this "
            "run; see the sex-inference numbers for why."
        )

    if rates.call_rate < LOW_CALL_RATE:
        out.append(
            f"overall call rate {rates.call_rate:.4f} is below {LOW_CALL_RATE}. "
            f"{rates.no_call} of {rates.total_markers} markers are uncalled."
        )

    worst = [
        c
        for c in rates.by_chrom
        if c.call_rate < LOW_CALL_RATE and c.total >= MIN_CHROM_LOCI_FOR_WARNING
    ]
    # A female Y is legitimately all no-call and is not a defect, so it is excluded here
    # rather than reported as a per-chromosome failure on every female sample.
    worst = [
        c for c in worst if not (c.chrom == Chrom.Y.value and sex.inferred is InferredSex.FEMALE)
    ]
    if worst:
        listed = ", ".join(f"{c.chrom}={c.call_rate:.3f}" for c in worst[:6])
        out.append(f"{len(worst)} chromosome(s) below the call-rate floor: {listed}")

    if het.autosomal_loci and not (
        LOW_AUTOSOMAL_HET <= het.autosomal_het_rate <= HIGH_AUTOSOMAL_HET
    ):
        out.append(
            f"autosomal heterozygosity {het.autosomal_het_rate:.4f} falls outside the "
            f"usual {LOW_AUTOSOMAL_HET}-{HIGH_AUTOSOMAL_HET} band. High suggests "
            "contamination or a mixed sample; low suggests autozygosity or a failed array."
        )

    if het_haploid:
        out.append(
            f"{het_haploid} heterozygous call(s) at loci inferred single-copy. A few are "
            "ordinary genotyping error; many would mean the sex inference is wrong."
        )

    if sex.inferred is InferredSex.FEMALE and sex.y_call_rate > FEMALE_MAX_Y_CALL:
        out.append(
            f"Y call rate {sex.y_call_rate:.4f} is higher than expected for an inferred "
            "female sample."
        )

    if duplicates.duplicate_positions:
        out.append(
            f"{duplicates.duplicate_positions} row(s) repeat a (chromosome, position) "
            "already present. Kept as-is: choosing between them is a matching decision, "
            "not an ingest one."
        )

    # Only chromosomes the *layout can name* count as missing. A vendor that does not
    # distinguish PAR has not lost it; the format never had it, and reporting that as a
    # gap sends the reader hunting for a region the file was never going to label. This
    # is the same structurally-absent-versus-uncalled distinction `infer_sex` makes for a
    # layout with no Y markers. An adapter that declares nothing falls back to the full
    # set, so the check still fires rather than silently going quiet.
    expected = (
        {Chrom(c) for c in representable_chroms} if representable_chroms else set(GRCH37_LENGTHS)
    )
    present = {Chrom(c) for c in table.frame.get_column("chrom").cast(pl.String).unique().to_list()}
    absent = expected - present
    if absent:
        out.append("no markers at all on: " + ", ".join(sorted(c.value for c in absent)) + ".")

    return tuple(out)


def run_qc(
    table: GenotypeTable,
    *,
    source: SourceInfo,
    anchors: tuple[BuildAnchor, ...] = ANCHORS,
) -> QCReport:
    """Compute the full QC report for a freshly parsed, ploidy-naive table."""
    rates = call_rates(table)
    het = heterozygosity(table)
    sex = infer_sex(table, het)
    build = check_build(table, declared=source.build, anchors=anchors)
    indels = indel_summary(table)
    duplicates = duplicate_summary(table)
    het_haploid = _count_het_haploid(table, sex.inferred)

    return QCReport(
        vendor=source.vendor,
        source_path=source.path,
        call_rates=rates,
        heterozygosity=het,
        sex=sex,
        build=build,
        indels=indels,
        duplicates=duplicates,
        het_haploid_calls=het_haploid,
        warnings=_warnings(
            rates,
            het,
            sex,
            build,
            duplicates,
            het_haploid,
            table,
            source.representable_chroms,
        ),
    )
