"""Private M9.2 score sums from original calls and native imputation dosages.

PLINK receives an allele-dose matrix, not a reinterpreted genomic VCF: each row's
ALT dose is already the biological effect-allele count. Synthetic diploid matrix
labels prevent chromosome import conventions from rescaling haploid observations.
Original loci, alleles, ploidies, quality and exclusions remain in the private result.
No percentile, outcome probability or confidence calibration is computed here.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import uuid
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, ClassVar

from genetics import __version__
from genetics.engine.matcher import complement, is_strand_ambiguous, strand_canonical
from genetics.external.plink2 import Plink2, Plink2Error
from genetics.imputation.dosages import DosageRecord, parse_record
from genetics.imputation.quality import ImputationEvidence
from genetics.ingest.schema import GenotypeTable
from genetics.paths import cache_dir, is_inside_repo, tools_manifest
from genetics.pgs.catalog import PgsError, fingerprint
from genetics.pgs.scoring import ScoreVariant, ScoringFile
from genetics.privacy import NoGenotypeRepr
from genetics.qc.report import InferredSex
from genetics.qc.sex_regions import PAR_GRCH37

SAMPLE = "SAMPLE"
UNSUPPORTED_FEATURES = {
    "is_haplotype",
    "is_diplotype",
    "is_interaction",
    "is_dominant",
    "is_recessive",
    "dosage_specific_weights",
    "special_calling_method",
    "conditional_inclusion",
    "variant_description",
}


@dataclass(frozen=True, repr=False)
class Dose(NoGenotypeRepr):
    _repr_fields: ClassVar[tuple[str, ...]] = ("status", "source", "ploidy")
    status: str
    value: float | None = None
    source: str | None = None
    ploidy: int | None = None
    dr2: float | None = None
    quality_scope: str | None = None
    dosage_method: str | None = None
    orientation: str | None = None
    native_record: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Private; even an aggregate dose identifies an observation."""
        return asdict(self)


@dataclass(frozen=True, repr=False)
class Term(NoGenotypeRepr):
    _repr_fields: ClassVar[tuple[str, ...]] = ("row_number",)
    row_number: int
    chrom: str | None
    position: int | None
    effect_allele: str
    other_allele: str | None
    weight: float | None
    fields: Mapping[str, str]
    features: tuple[str, ...]
    before: Dose
    after: Dose

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, repr=False)
class ScoreResult(NoGenotypeRepr):
    _repr_fields: ClassVar[tuple[str, ...]] = ("pgs_id", "status")
    pgs_id: str
    status: str
    record: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Private JSON, containing personal scores and marker-level evidence."""
        return {"schema_version": 1, "kind": "pgs_score", **self.record}


def _ploidy(chrom: str | None, position: int | None, sex: InferredSex) -> int | None:
    if chrom in {str(i) for i in range(1, 23)}:
        return 2
    if chrom == "X" and position is not None:
        if any(start <= position <= end for start, end in PAR_GRCH37["X"]):
            return 2
        return 1 if sex is InferredSex.MALE else 2 if sex is InferredSex.FEMALE else None
    return None


def _pair(row: ScoreVariant) -> tuple[str, str] | None:
    other = row.fields.get("other_allele") or row.fields.get("hm_inferOtherAllele")
    if not re.fullmatch(r"[ACGT]+", row.effect_allele):
        return None
    if other is None or not re.fullmatch(r"[ACGT]+", other) or other == row.effect_allele:
        return None
    return row.effect_allele, other


def _direct(
    row: ScoreVariant,
    probes: Sequence[Mapping[str, Any]],
    sex: InferredSex,
) -> Dose:
    if not probes:
        return Dose("marker_absent")
    called = [p for p in probes if p["call_status"] != "no_call" and p["genotype"] is not None]
    if not called:
        return Dose("no_call")
    pair = _pair(row)
    if pair is None:
        return Dose("allele_contract_missing")
    ambiguous = is_strand_ambiguous(pair)
    if any(len(allele) != 1 for allele in pair):
        return Dose("indel_excluded")
    groups = {
        str(p["genotype"]) if ambiguous else strand_canonical(str(p["genotype"])) for p in called
    }
    if len(groups) != 1:
        return Dose("duplicate_conflict")
    ploidy = _ploidy(row.chrom, row.position, sex)
    if ploidy is None:
        return Dose("ploidy_unresolved")
    for probe in called:
        gt = probe["genotype"]
        if (
            not isinstance(gt, str)
            or len(gt) != 2
            or gt != "".join(sorted(str(probe["a1"]) + str(probe["a2"])))
        ):
            raise PgsError("Malformed normalized observation; scoring refused.")
        if probe["call_status"] == "het_haploid":
            return Dose("ploidy_conflict")
        if probe["call_status"] not in {"called", "hemizygous"}:
            raise PgsError("Unknown normalized call status; scoring refused.")
        if "I" in gt or "D" in gt:
            return Dose("indel_excluded")
        if (ploidy == 1 and (probe["call_status"] != "hemizygous" or gt[0] != gt[1])) or (
            ploidy == 2 and probe["call_status"] != "called"
        ):
            return Dose("ploidy_conflict")
    genotype = str(called[0]["genotype"])
    declared = set(pair)
    orientation = "as_written"
    if not set(genotype) <= declared:
        if not set(complement(genotype)) <= declared:
            return Dose("allele_mismatch")
        genotype = complement(genotype)
        orientation = "complemented" if len(set(genotype)) == 2 else "complemented_inferred"
    if ambiguous and genotype.count(row.effect_allele) != complement(genotype).count(
        row.effect_allele
    ):
        return Dose("strand_ambiguous")
    dose = float(genotype.count(row.effect_allele)) * ploidy / 2
    return Dose(
        "observed",
        dose,
        "direct",
        ploidy,
        None,
        "not_estimated",
        "observed_allele_count",
        orientation,
    )


def _imputed(
    row: ScoreVariant,
    records: Sequence[DosageRecord],
    sex: InferredSex,
) -> Dose:
    if not records:
        return Dose("no_imputed_observation")
    if len(records) != 1:
        return Dose("ambiguous_panel_records")
    raw = records[0]
    if raw.status != "resolved":
        return Dose("ploidy_conflict")
    record = parse_record(raw.to_dict())
    if record.ploidy != _ploidy(row.chrom, row.position, sex):
        return Dose("ploidy_conflict")
    pair = _pair(row)
    if pair is None:
        return Dose("allele_contract_missing")
    alleles = {record.ref, *record.alt}
    # Both score alleles must describe this reference locus. A second ALT does not
    # change an allele's dose, but its REF quality stays unknown without covariance.
    orientation = "as_written"
    effect = row.effect_allele
    snv = all(len(a) == 1 for a in pair)
    if (
        snv
        and not is_strand_ambiguous(pair)
        and set(pair) <= alleles
        and {complement(a) for a in pair} <= alleles
    ):
        return Dose(
            "strand_ambiguous",
            source=record.source,
            ploidy=record.ploidy,
            native_record=record.to_dict(),
        )
    if not set(pair) <= alleles:
        if not snv:
            return Dose(
                "allele_mismatch",
                source=record.source,
                ploidy=record.ploidy,
                native_record=record.to_dict(),
            )
        flipped = tuple(complement(a) for a in pair)
        if not set(flipped) <= alleles:
            return Dose("allele_mismatch")
        effect = complement(effect)
        orientation = "complemented"
    if record.source == "direct":
        dose = (
            float(record.genotype.count((record.ref, *record.alt).index(effect)))
            if record.genotype is not None
            else None
        )
        quality = None
    else:
        dose, quality = ImputationEvidence.from_record(record).allele_dosage(effect)
    if dose is None:
        return Dose("no_call")
    if is_strand_ambiguous(pair):
        opposite = complement(effect)
        if record.source == "direct":
            alternate = (
                float(record.genotype.count((record.ref, *record.alt).index(opposite)))
                if record.genotype is not None
                else None
            )
        else:
            alternate, _ = ImputationEvidence.from_record(record).allele_dosage(opposite)
        if dose != alternate:
            return Dose("strand_ambiguous")
    return Dose(
        "observed",
        dose,
        record.source,
        record.ploidy,
        quality,
        record.quality_scope,
        record.dosage_method,
        orientation,
        record.to_dict(),
    )


def _original(row: ScoreVariant, probes: Sequence[Mapping[str, Any]], sex: InferredSex) -> Dose:
    dose = _direct(row, probes, sex)
    if not probes:
        return dose
    return replace(
        dose,
        source="direct",
        native_record={
            "kind": "original_array",
            "probes": [dict(probe) for probe in probes],
        },
    )


def _unusable(row: ScoreVariant) -> str | None:
    if UNSUPPORTED_FEATURES.intersection(row.features):
        return "unsupported_model"
    if row.chrom not in {*(str(i) for i in range(1, 23)), "X"}:
        return "unsupported_chromosome" if row.chrom is not None else "unresolved_locus"
    if row.position is None:
        return "unresolved_locus"
    if _pair(row) is None:
        return "allele_contract_missing"
    if "harmonization_mismatch" in row.features:
        return "harmonization_mismatch"
    return None


def _number(value: str) -> float:
    try:
        result = float(value)
    except ValueError as exc:
        raise PgsError("Malformed PLINK score report.") from exc
    if not math.isfinite(result):
        raise PgsError("Nonfinite PLINK score report.")
    return result


def _native_sum(
    terms: Sequence[Term],
    phase: str,
    *,
    root: Path,
    plink: Plink2,
) -> dict[str, Any]:
    usable = [
        (term, getattr(term, phase)) for term in terms if getattr(term, phase).status == "observed"
    ]
    if not usable:
        return {"status": "no_usable_observations", "sum": None, "terms": 0, "native_alleles": 0}
    vcf = root / f"{phase}.pgs-dose-matrix.vcf"
    weights = root / f"{phase}.pgs-weights.tsv"
    expected_ids = {f"TERM_{term.row_number}" for term, _ in usable}
    with (
        vcf.open("w", encoding="utf-8", newline="") as data,
        weights.open("w", encoding="utf-8", newline="") as w,
    ):
        data.write(
            "##fileformat=VCFv4.2\n##contig=<ID=1>\n"
            "##source=genetics-analysis-effect-dose-matrix\n"
            '##FORMAT=<ID=GT,Number=1,Type=String,Description="Computational matrix hardcall">\n'
            '##FORMAT=<ID=DS,Number=A,Type=Float,Description="Native biological effect dose">\n'
            f"#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\t{SAMPLE}\n"
        )
        w.write("ID\tALLELE\tWEIGHT\n")
        for term, dose in usable:
            if dose.value is None or term.weight is None or dose.ploidy is None:
                raise PgsError("Incomplete score observation.")
            if not math.isfinite(dose.value) or not 0 <= dose.value <= dose.ploidy:
                raise PgsError("Invalid native effect-allele dose.")
            token = f"TERM_{term.row_number}"
            data.write(
                f"1\t{term.row_number}\t{token}\tC\tA\t.\tPASS\t.\tGT:DS\t./.:{dose.value:.17g}\n"
            )
            w.write(f"{token}\tA\t{term.weight:.17g}\n")
    prefix = root / phase
    args = [
        "--vcf",
        str(vcf),
        "dosage=DS",
        "--dosage-erase-threshold",
        "0",
        "--score",
        str(weights),
        "1",
        "2",
        "3",
        "header-read",
        "no-mean-imputation",
        "cols=nallele,denom,dosagesum,scoresums",
        "list-variants",
        "--threads",
        "1",
        "--memory",
        "1024",
    ]
    try:
        plink.run(args, out=prefix)
        lines = prefix.with_suffix(".sscore").read_text(encoding="utf-8").splitlines()
        if len(lines) != 2:
            raise PgsError("PLINK must report exactly one scored target.")
        columns, values = lines[0].lstrip("#").split(), lines[1].split()
        if len(columns) != len(set(columns)) or len(values) != len(columns):
            raise PgsError("Malformed PLINK score columns.")
        report = dict(zip(columns, values, strict=True))
        if (
            not {"IID", "ALLELE_CT", "DENOM", "WEIGHT_SUM", "NAMED_ALLELE_DOSAGE_SUM"}
            <= report.keys()
            or report["IID"] != SAMPLE
        ):
            raise PgsError("PLINK report has the wrong target or columns.")
        if report["ALLELE_CT"] != str(2 * len(usable)) or report["DENOM"] != str(2 * len(usable)):
            raise PgsError("PLINK did not score every usable matrix observation.")
        used = (
            prefix.with_name(prefix.name + ".sscore.vars").read_text(encoding="utf-8").splitlines()
        )
        if len(used) != len(expected_ids) or set(used) != expected_ids:
            raise PgsError("PLINK's scored term identities disagree with the matched observations.")
        actual = _number(report["WEIGHT_SUM"])
        native_dose_sum = math.fsum(float(d.value) for _, d in usable if d.value is not None)
        input_sum = math.fsum(
            float(t.weight) * float(d.value)
            for t, d in usable
            if t.weight is not None and d.value is not None
        )
        quantization = (
            math.fsum(abs(float(t.weight)) for t, _ in usable if t.weight is not None) / 32768
        )
        # PGEN dosage resolution is 1/16384 on this diploid computational matrix.
        # The text report uses six significant digits; include its last printed unit.
        rounding = 10 ** (math.floor(math.log10(abs(actual))) - 5) if actual else 0.000001
        tolerance = quantization + rounding + 1e-10 * max(1.0, abs(input_sum))
        if abs(actual - input_sum) > tolerance:
            raise PgsError("PLINK sum disagrees with native effect-dose arithmetic.")
        dosage_tolerance = len(usable) / 32768 + 0.00001 * max(1.0, abs(native_dose_sum))
        if abs(_number(report["NAMED_ALLELE_DOSAGE_SUM"]) - native_dose_sum) > dosage_tolerance:
            raise PgsError("PLINK dosage total disagrees with the effect-dose matrix.")
        return {
            "status": "scored" if len(usable) == len(terms) else "scored_partial",
            "sum": actual,
            "terms": len(usable),
            "native_alleles": sum(int(d.ploidy) for _, d in usable if d.ploidy is not None),
            "input_dose_arithmetic_sum": input_sum,
            "verification_bound": tolerance,
            "plink_matrix_allele_ct": 2 * len(usable),
            "plink_matrix_denom": 2 * len(usable),
            "report_sha256": fingerprint(prefix.with_suffix(".sscore"))["sha256"],
            "matrix_sha256": fingerprint(vcf)["sha256"],
            "weights_sha256": fingerprint(weights)["sha256"],
            "parameters": {
                "dosage_erase_threshold": 0,
                "missing": "no_mean_imputation",
                "report": "sum",
                "threads": 1,
                "memory_mb": 1024,
            },
        }
    except (OSError, OverflowError, Plink2Error) as exc:
        raise PgsError(
            "PLINK score execution or validation failed; no score result accepted."
        ) from exc
    finally:
        # Personal matrix/selection intermediates are private and also gitignored.
        vcf.unlink(missing_ok=True)
        weights.unlink(missing_ok=True)


def score(
    scoring: ScoringFile,
    *,
    table: GenotypeTable | None,
    dosages: Iterable[DosageRecord] | None = None,
    sex: InferredSex,
    no_impute: bool = False,
    allow_restricted: bool = False,
    plink: Plink2 | None = None,
    workspace: Path | None = None,
    allow_in_repo: bool = False,
    ancestry: Mapping[str, Any] | None = None,
    imputation_provenance: Mapping[str, Any] | None = None,
    progress: Callable[[str], None] | None = None,
) -> ScoreResult:
    """Shared low-level engine; explicitly disabled imputation is the only direct-only mode.

    A validated saved dosage iterator can score after imputation without an original
    array. Its before-imputation result is then unavailable, never reconstructed from
    the partial stage-direct stream. Low quality and unknown phase quality are retained.
    """
    if any(type(v) is not bool for v in (no_impute, allow_restricted, allow_in_repo)):
        raise PgsError("Scoring mode flags must be explicit booleans.")
    if no_impute and (dosages is not None or table is None):
        raise PgsError("Direct-only scoring requires the original array and no dosage stream.")
    if not no_impute and dosages is None:
        raise PgsError(
            "Default scoring requires imputation; choose --no-impute explicitly to opt out."
        )
    if not isinstance(sex, InferredSex) or scoring.build != "GRCh37":
        raise PgsError("Scoring requires GRCh37 coordinates and explicit inferred sex.")
    try:
        scoring.metadata.license.require_usable(opt_in=allow_restricted)
    except ValueError as exc:
        raise PgsError(str(exc)) from exc
    rows = list(scoring.iter_variants())  # exhaustion validates all rows and source identity
    loci = {(r.chrom, r.position) for r in rows if r.chrom is not None and r.position is not None}
    probes: dict[tuple[str, int], list[Mapping[str, Any]]] = {}
    input_digest = None
    if table is not None:
        digest = hashlib.sha256()
        for probe in table.frame.iter_rows(named=True):
            digest.update(json.dumps(probe, sort_keys=True, separators=(",", ":")).encode())
            digest.update(b"\n")
            locus = (str(probe["chrom"]), int(probe["pos_grch37"]))
            if locus in loci:
                probes.setdefault(locus, []).append(probe)
        input_digest = digest.hexdigest()
    records: dict[tuple[str, int], list[DosageRecord]] = {}
    dosage_digest = hashlib.sha256() if dosages is not None else None
    if dosages is not None:
        for count, record in enumerate(dosages, 1):
            if not isinstance(record, DosageRecord):
                raise PgsError("The scoring dosage iterator returned an invalid record type.")
            if dosage_digest is not None:
                dosage_digest.update(
                    json.dumps(record.to_dict(), sort_keys=True, separators=(",", ":")).encode()
                )
                dosage_digest.update(b"\n")
            locus = (record.chrom, record.pos_grch37)
            if locus in loci:
                records.setdefault(locus, []).append(record)
            if progress and count % 500_000 == 0:
                progress("Reading native dosage evidence for PGS scoring")
    terms: list[Term] = []
    for row in rows:
        locus = (row.chrom or "", row.position or 0)
        reason = _unusable(row)
        before = (
            Dose(reason)
            if reason
            else Dose("not_recorded")
            if table is None
            else _original(row, probes.get(locus, []), sex)
        )
        if no_impute:
            after = Dose("disabled")
        elif reason:
            after = Dose(reason)
        elif table is not None and before.status not in {"marker_absent", "no_call"}:
            after = before  # original called probes always retain precedence, including failures
        else:
            after = _imputed(row, records.get(locus, []), sex)
            if table is not None and after.source == "direct":
                raise PgsError(
                    "Stage-direct dosage cannot replace an absent or uncalled original probe."
                )
        pair = _pair(row)
        terms.append(
            Term(
                row.row_number,
                row.chrom,
                row.position,
                row.effect_allele,
                None if pair is None else pair[1],
                row.effect_weight,
                row.fields,
                row.features,
                before,
                after,
            )
        )
    unsupported = any(UNSUPPORTED_FEATURES.intersection(t.features) for t in terms)
    root = workspace if workspace is not None else cache_dir() / "pgs" / uuid.uuid4().hex
    if is_inside_repo(root) and not allow_in_repo:
        raise PgsError(
            "Personal scoring output must be outside the checkout; "
            "in-repo paths require explicit opt-in."
        )
    if unsupported:
        before_result = after_result = {
            "status": "unsupported_model",
            "sum": None,
            "terms": 0,
            "native_alleles": 0,
        }
        native_version = None
        native_sha = None
    else:
        root.mkdir(parents=True, exist_ok=True)
        native = plink or Plink2.discover()
        native_sha = fingerprint(native.path)["sha256"] if native.path.is_file() else None
        if progress and table is not None:
            progress("Computing original-array PGS sum with pinned PLINK")
        before_result = (
            {"status": "not_recorded", "sum": None, "terms": 0, "native_alleles": 0}
            if table is None
            else _native_sum(terms, "before", root=root, plink=native)
        )
        if progress and not no_impute:
            progress("Computing post-imputation PGS sum with pinned PLINK")
        after_result = (
            {"status": "disabled", "sum": None, "terms": 0, "native_alleles": 0}
            if no_impute
            else _native_sum(terms, "after", root=root, plink=native)
        )
        native_version = native.version
        if native_sha is not None and fingerprint(native.path)["sha256"] != native_sha:
            raise PgsError("The PLINK binary changed during scoring; no result accepted.")
    payload: dict[str, Any] = {
        "pgs_id": scoring.headers["pgs_id"],
        "status": "unsupported_model"
        if unsupported
        else "computed"
        if before_result["sum"] is not None or after_result["sum"] is not None
        else "no_usable_observations",
        "score_definition": scoring.inspect(),
        "original_table_sha256": input_digest,
        "dosage_stream_sha256": dosage_digest.hexdigest() if dosage_digest is not None else None,
        "inferred_sex": sex.value,
        "imputation_mode": "disabled" if no_impute else "enabled",
        "imputation_provenance": None
        if imputation_provenance is None
        else dict(imputation_provenance),
        "ancestry": None if ancestry is None else dict(ancestry),
        "portability": "not_computed_M9.5",
        "percentile": None,
        "allow_restricted": allow_restricted,
        "plink_version": native_version,
        "plink_sha256": native_sha,
        "tool_manifest_sha256": fingerprint(tools_manifest())["sha256"],
        "engine_version": __version__,
        "method_version": 1,
        "method": "PLINK --score native-effect-dose matrix; synthetic diploid matrix labels",
        "before": before_result,
        "after": after_result,
        "term_states": {
            name: dict(sorted(Counter(getattr(t, name).status for t in terms).items()))
            for name in ("before", "after")
        },
        "terms": [term.to_dict() for term in terms],
    }
    return ScoreResult(scoring.headers["pgs_id"], payload["status"], payload)


def write_result(
    result: ScoreResult, path: Path | None = None, *, allow_in_repo: bool = False
) -> Path:
    """Publish a private score atomically; an existing result is never overwritten."""
    destination = path or cache_dir() / "pgs" / f"{uuid.uuid4().hex}.pgs-score.json"
    if not destination.name.endswith(".pgs-score.json"):
        raise PgsError("A personal score output must use the .pgs-score.json suffix.")
    if is_inside_repo(destination) and not allow_in_repo:
        raise PgsError(
            "Personal score output requires an outside-checkout path or explicit opt-in."
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        raise PgsError("The requested score output already exists; choose a new path.")
    pending = destination.with_name(destination.name + f".{uuid.uuid4().hex}.part")
    try:
        with pending.open("x", encoding="utf-8", newline="") as handle:
            json.dump(result.to_dict(), handle, sort_keys=True, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        # Hard-link publication is atomic and refuses a destination created concurrently.
        os.link(pending, destination)
    except (OSError, ValueError) as exc:
        raise PgsError("Could not publish the private score result.") from exc
    finally:
        pending.unlink(missing_ok=True)
    return destination
