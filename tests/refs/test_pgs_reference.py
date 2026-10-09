"""M9.4 reference distributions on a fabricated 1000 Genomes-shaped panel.

Every panel genotype here is drawn from invented allele frequencies with a fixed seed;
sample IDs are synthetic. No real panel file or personal export is read.
"""

from __future__ import annotations

import gzip
import json
import math
import os
import random
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

import pytest
from test_pgs_engine import definition, dosage, probe, table, weight
from typer.testing import CliRunner

from genetics.ancestry.context import PopulationResult
from genetics.cli.main import app
from genetics.external.plink2 import Plink2, Plink2ResultInfo
from genetics.paths import reference_manifest
from genetics.pgs import reference
from genetics.pgs.catalog import Catalog, PgsError, fingerprint
from genetics.pgs.engine import reference_matrix_sums, score, write_result
from genetics.pgs.reference import (
    PANEL_SOURCE,
    attach_reference,
    discover_panel,
    extract,
    group_statistics,
    read_placement,
)
from genetics.qc.report import InferredSex
from genetics.refs import lock as refs_lock
from genetics.refs import manifest as refs_manifest

POPS = (("PA", "SP1"), ("PB", "SP1"), ("PC", "SP2"))


class MultiPlink(Plink2):
    """Scores every matrix column from its DS values, like the pinned binary would."""

    mode = "good"

    def run(
        self,
        args: Sequence[str],
        *,
        out: Path,
        cwd: Path | None = None,
        timeout: float | None = None,
    ) -> Plink2ResultInfo:
        assert "no-mean-imputation" in args and "dosage=DS" in args
        matrix = Path(args[args.index("--vcf") + 1]).read_text().splitlines()
        weights = Path(args[args.index("--score") + 1]).read_text().splitlines()[1:]
        coefficient = {line.split()[0]: float(line.split()[2]) for line in weights}
        header = next(line for line in matrix if line.startswith("#CHROM")).split("\t")
        samples = header[9:]
        records = [line.split("\t") for line in matrix if not line.startswith("#")]
        rows = ["#IID\tALLELE_CT\tDENOM\tNAMED_ALLELE_DOSAGE_SUM\tWEIGHT_SUM"]
        for index, sample in enumerate(samples):
            doses = [float(r[9 + index].split(":")[1]) for r in records]
            total = math.fsum(d * coefficient[r[2]] for d, r in zip(doses, records, strict=True))
            if self.mode == "wrong_sum" and index == len(samples) - 1:
                total += 1
            name = "OTHER" if self.mode == "wrong_samples" and index == 0 else sample
            count = 2 * len(records)
            rows.append(f"{name}\t{count}\t{count}\t{sum(doses)}\t{total:.6g}")
        out.with_suffix(".sscore").write_text("\n".join(rows) + "\n", encoding="utf-8")
        out.with_name(out.name + ".sscore.vars").write_text(
            "\n".join(r[2] for r in records) + "\n", encoding="utf-8"
        )
        return Plink2ResultInfo(tuple(args), 0, "", "", out, out.with_suffix(".log"), ())


@pytest.fixture
def fake() -> MultiPlink:
    return MultiPlink(Path("synthetic-plink"), "synthetic-test")


def _filename(chrom: str) -> str:
    source = refs_manifest.load(reference_manifest()).get(PANEL_SOURCE)
    return next(f.filename for f in source.files if f.filename.startswith(f"ALL.chr{chrom}."))


def build_panel(
    root: Path,
    records: dict[str, list[tuple[int, str, str, list[str]]]],
    *,
    n: int = 30,
    lock: bool = True,
) -> dict[str, Any]:
    """Write a synthetic panel: labels, gzipped VCFs and a lock pinning both."""
    source = refs_manifest.load(reference_manifest()).get(PANEL_SOURCE)
    directory = root / PANEL_SOURCE
    directory.mkdir(parents=True, exist_ok=True)
    samples = [f"SYN{i:04d}" for i in range(n)]
    sexes = ["male" if i % 2 else "female" for i in range(n)]
    pops = [POPS[i % 3] for i in range(n)]
    labels = next(f.filename for f in source.files if f.filename.endswith(".panel"))
    (directory / labels).write_text(
        "sample\tpop\tsuper_pop\tgender\n"
        + "".join(
            f"{s}\t{p}\t{sp}\t{sex}\n" for s, (p, sp), sex in zip(samples, pops, sexes, strict=True)
        ),
        encoding="utf-8",
    )
    names = [labels]
    for chrom, rows in records.items():
        name = _filename(chrom)
        names.append(name)
        body = "##fileformat=VCFv4.1\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\t"
        body += "\t".join(samples) + "\n"
        for position, ref, alt, calls in rows:
            body += f"{chrom}\t{position}\t.\t{ref}\t{alt}\t100\tPASS\t.\tGT\t" + "\t".join(calls)
            body += "\n"
        with gzip.open(directory / name, "wt", encoding="utf-8", newline="\n") as handle:
            handle.write(body)
    if lock:
        files = {
            name: refs_lock.LockedFile(
                "https://example.invalid/" + name,
                fingerprint(directory / name)["sha256"],
                (directory / name).stat().st_size,
                "2026-10-09",
            )
            for name in names
        }
        refs_lock.write(
            root / "manifest.lock",
            refs_lock.Lock(
                sources={
                    PANEL_SOURCE: refs_lock.LockedSource(source.version, source.license_id, files)
                }
            ),
        )
    return {"samples": samples, "sexes": sexes, "pops": pops}


def calls(n: int, frequency: float, *, seed: int, haploid_males: bool = False) -> list[str]:
    rng = random.Random(seed)
    out = []
    for i in range(n):
        alleles = [str(int(rng.random() < frequency)) for _ in range(2)]
        out.append(alleles[0] if haploid_males and i % 2 else "|".join(alleles))
    return out


class Stub:
    """A placement result as M5.5 would serialize it; only ``to_dict`` is read."""

    def __init__(self, status: str, population: str | None = None, region: str | None = None):
        self.data = {
            "status": status,
            "population": population,
            "region": region,
            "reason": "" if status == "placed" else "Synthetic decline: no population fits.",
        }

    def to_dict(self) -> dict[str, Any]:
        return dict(self.data)


def placed(population: str = "PA", region: str = "SP1") -> PopulationResult:
    return cast(PopulationResult, Stub("placed", population, region))


def standard(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    root = tmp_path / "refs"
    n = 30
    info = build_panel(
        root,
        {
            "1": [
                (101, "C", "A", calls(n, 0.3, seed=1)),  # as written
                (102, "T", "G", calls(n, 0.4, seed=2)),  # complemented A/C
                (103, "A", "T", calls(n, 0.5, seed=3)),  # palindromic
                (105, "C", "A", calls(n, 0.2, seed=5)),  # SNP and an indel at one locus
                (105, "C", "CT", calls(n, 0.1, seed=6)),
                (106, "C", "A", calls(n, 0.2, seed=7)),  # two compatible records
                (106, "C", "A,G", calls(n, 0.2, seed=8)),
                (107, "A", "C,G,T", calls(n, 0.2, seed=9)),  # four alleles
                (108, "C", "A", [*calls(n - 1, 0.2, seed=10), ".|0"]),  # missing call
                (109, "A", "AG", calls(n, 0.3, seed=11)),  # sequence-resolved indel
                (110, "G", "C", calls(n, 0.3, seed=12)),  # allele mismatch
            ],
            "X": [
                (10_000_000, "C", "A", calls(n, 0.3, seed=13, haploid_males=True)),
                (10_000_001, "C", "A", calls(n, 0.3, seed=14)),  # males diploid: conflict
                (100_001, "C", "A", calls(n, 0.3, seed=15)),  # PAR: diploid for everyone
            ],
        },
        n=n,
    )
    return root, info


ROWS = [
    weight(101, value="0.5"),
    weight(102, value="-0.25"),
    weight(103, effect="A", other="T", value="1"),
    weight(104, value="1"),
    weight(105, value="0.75"),
    weight(106, value="1"),
    weight(107, value="1"),
    weight(108, value="1"),
    weight(109, effect="AG", other="A", value="0.4"),
    weight(110, value="1"),
    weight(10_000_000, chrom="X", value="2"),
    weight(10_000_001, chrom="X", value="1"),
    weight(100_001, chrom="X", value="-1"),
]


def test_extraction_applies_the_shared_allele_and_ploidy_rules(tmp_path: Path) -> None:
    root, info = standard(tmp_path)
    scoring = definition(tmp_path / "def", ROWS)
    panel = discover_panel(root)
    assert not isinstance(panel, str)
    result = extract(scoring, panel, workers=1)
    assert not isinstance(result, str)
    assert result.states == {
        1: "reference_resolved",
        2: "reference_resolved",
        3: "strand_ambiguous",
        4: "not_in_reference",
        5: "reference_resolved",
        6: "ambiguous_panel_records",
        7: "strand_ambiguous",
        8: "reference_missing_call",
        9: "reference_resolved",
        10: "allele_mismatch",
        11: "reference_resolved",
        12: "reference_ploidy_conflict",
        13: "reference_resolved",
    }
    original = calls(30, 0.3, seed=1)
    assert list(result.doses[1]) == [t.count("1") for t in original]
    # Complemented: effect A of a score A/C at a T/G record is T, the REF (index 0).
    assert list(result.doses[2]) == [t.count("0") for t in calls(30, 0.4, seed=2)]
    # Haploid males stay on a 0-1 scale; females count both copies.
    haploid = calls(30, 0.3, seed=13, haploid_males=True)
    assert list(result.doses[11]) == [t.count("1") for t in haploid]
    assert max(result.doses[11][1::2]) <= 1
    assert list(result.samples) == info["samples"]


def test_unlocked_absent_and_tampered_panels(tmp_path: Path) -> None:
    root, _ = standard(tmp_path)
    scoring = definition(tmp_path / "def", [weight(101), weight(5000, chrom="2")])
    panel = discover_panel(root)
    assert not isinstance(panel, str)
    missing = extract(scoring, panel, workers=1)
    assert isinstance(missing, str) and "chromosome(s) 2" in missing
    assert isinstance(discover_panel(tmp_path / "empty"), str)
    (root / "manifest.lock").unlink()
    assert isinstance(discover_panel(root), str)
    root2, _ = standard(tmp_path / "second")
    vcf = root2 / PANEL_SOURCE / _filename("1")
    # A valid gzip whose content differs from what the lock pinned (one call changed).
    text = gzip.decompress(vcf.read_bytes()).decode()
    vcf.write_bytes(gzip.compress(text.replace("0|0", "1|1", 1).encode()))
    panel2 = discover_panel(root2)
    assert not isinstance(panel2, str)
    with pytest.raises(PgsError, match="lock digest"):
        extract(definition(tmp_path / "d2", [weight(101)]), panel2, workers=1)


def test_extraction_cache_is_reused_and_rebuilt_when_corrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path / "appdata"))
    root, _ = standard(tmp_path)
    scoring = definition(tmp_path / "def", ROWS)
    panel = discover_panel(root)
    assert not isinstance(panel, str)
    first = extract(scoring, panel, workers=1)
    assert not isinstance(first, str)
    cache = next((tmp_path / "appdata").rglob("*.pgs-reference.tsv.gz"))
    native = reference._extract_chromosome

    def forbidden(*args: Any) -> Any:
        pytest.fail("a valid cache must not reread the panel")

    monkeypatch.setattr(reference, "_extract_chromosome", forbidden)
    again = extract(scoring, panel, workers=1)
    assert not isinstance(again, str)
    assert again.doses == first.doses and again.states == first.states
    cache.write_bytes(gzip.compress(b"not a cache\n"))
    monkeypatch.setattr(reference, "_extract_chromosome", native)
    rebuilt = extract(scoring, panel, workers=1)
    assert not isinstance(rebuilt, str) and rebuilt.doses == first.doses


def test_group_statistics_mid_rank_wilson_quantiles_and_histogram() -> None:
    stats = group_statistics([1.0, 2.0, 3.0, 4.0], 2.0)
    assert stats["below"] == 1 and stats["ties"] == 1
    assert stats["percentile"] == 37.5
    p, n, z = 0.375, 4, 1.959963984540054
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    assert stats["percentile_interval_95"] == pytest.approx(
        [100 * (centre - half), 100 * (centre + half)]
    )
    assert stats["quantiles"]["50"] == 2.5 and stats["quantiles"]["25"] == 1.75
    assert stats["sd"] == pytest.approx(math.sqrt(5 / 3))
    assert sum(stats["histogram"]["counts"]) == 4
    assert stats["histogram"]["counts"][-1] == 1  # the maximum lands in the last bin
    flat = group_statistics([3.0, 3.0], 5.0)
    assert flat["percentile"] == 100.0 and flat["histogram"]["counts"] == [2]
    with pytest.raises(PgsError):
        group_statistics([], 0.0)


def person(tmp_path: Path, fake: MultiPlink, **kwargs: Any) -> Any:
    scoring = definition(tmp_path / "def", ROWS)
    probes = [probe(101, copies=2), probe(102), probe(103, copies=1, effect="A", other="T")]
    kwargs.setdefault("table", table(probes))
    kwargs.setdefault("dosages", [dosage(105, values=(0.5,)), dosage(109, ref="A", alt=("AG",))])
    result = score(
        scoring,
        sex=InferredSex.FEMALE,
        plink=fake,
        workspace=tmp_path / "work",
        **kwargs,
    )
    return scoring, result


def test_placed_person_is_ranked_within_super_population_over_comparable_rows(
    tmp_path: Path, fake: MultiPlink
) -> None:
    root, info = standard(tmp_path)
    scoring, result = person(tmp_path, fake)
    attached = attach_reference(
        result,
        scoring,
        table=None,
        references_root=root,
        plink=fake,
        workspace=tmp_path / "ref",
        workers=1,
        placement=placed(),
    ).record
    block = attached["reference_distribution"]
    assert block["status"] == "computed" and block["group"]["ancestry_matched"] is True
    after = block["after"]
    # Rows 101, 102 (chip), 103 palindromic het (chip), 105 and 109 (imputed) are observed.
    assert after["person_scored_rows"] == 5
    assert after["comparable_rows"] == [1, 2, 5, 9]
    assert after["excluded_for_reference"] == {"strand_ambiguous": 1}
    expected_person = 0.5 * 2 + (-0.25) * 1 + 0.75 * 0.5 + 0.4 * 1.25
    assert after["person_sum"] == pytest.approx(expected_person)
    assert after["person_dose_basis"]["sources"] == {"direct": 2, "imputed_untyped": 2}
    panel = discover_panel(root)
    assert not isinstance(panel, str)
    extraction = extract(scoring, panel, workers=1)
    assert not isinstance(extraction, str)
    weights = {1: 0.5, 2: -0.25, 5: 0.75, 9: 0.4}
    exact = [math.fsum(w * extraction.doses[r][i] for r, w in weights.items()) for i in range(30)]
    assert after["reference_sums"] == pytest.approx(exact, abs=1e-5)
    groups = after["groups"]
    members = [i for i, (_, sp) in enumerate(info["pops"]) if sp == "SP1"]
    assert groups["super_population"]["label"] == "SP1"
    assert groups["super_population"]["n"] == len(members) == 20
    assert groups["population"]["label"] == "PA" and groups["population"]["n"] == 10
    assert groups["pooled"]["n"] == 30
    assert after["primary_group"] == "super_population"
    assert after["percentile"] == groups["super_population"]["percentile"]
    assert attached["percentile"]["after"] == after["percentile"]
    before = block["before"]
    assert before["comparable_rows"] == [1, 2] and before["status"] == "placed"
    assert block["panel"]["n_samples"] == 30
    assert not list((tmp_path / "ref").glob("*.vcf"))


def test_declined_and_saved_only_people_use_the_pooled_panel_unmatched(
    tmp_path: Path, fake: MultiPlink
) -> None:
    root, _ = standard(tmp_path)
    scoring, result = person(tmp_path, fake)
    declined = attach_reference(
        result,
        scoring,
        table=None,
        references_root=root,
        plink=fake,
        workspace=tmp_path / "ref",
        workers=1,
        placement=cast(PopulationResult, Stub("declined")),
    ).record["reference_distribution"]
    assert declined["group"]["ancestry_matched"] is False
    assert declined["group"]["reason"] == "Synthetic decline: no population fits."
    assert declined["after"]["primary_group"] == "pooled"
    assert declined["after"]["groups"]["super_population"] is None
    saved_scoring, saved = person(tmp_path / "saved", fake, table=None)
    record = attach_reference(
        saved,
        saved_scoring,
        table=None,
        references_root=root,
        plink=fake,
        workspace=tmp_path / "ref2",
        workers=1,
    ).record
    block = record["reference_distribution"]
    assert "no original array" in block["group"]["reason"]
    assert block["before"] == {
        "status": "unavailable",
        "reason": "not_recorded",
        "percentile": None,
    }
    assert record["percentile"]["before"] is None


def test_disabled_not_run_and_opted_out_phases_are_explicit(
    tmp_path: Path, fake: MultiPlink
) -> None:
    scoring, result = person(tmp_path, fake, no_impute=True, dosages=None)
    absent = attach_reference(result, scoring, table=None, references_root=tmp_path / "none")
    assert absent.record["reference_distribution"]["status"] == "not_run"
    assert "genetics refs fetch" in absent.record["reference_distribution"]["reason"]
    off = attach_reference(result, scoring, table=None, enabled=False)
    assert off.record["reference_distribution"]["status"] == "disabled"
    assert off.record["percentile"] == {"before": None, "after": None}
    with pytest.raises(PgsError, match="booleans"):
        attach_reference(result, scoring, table=None, enabled=cast(bool, "no"))
    root, _ = standard(tmp_path)
    block = attach_reference(
        result,
        scoring,
        table=None,
        references_root=root,
        plink=fake,
        workspace=tmp_path / "ref",
        workers=1,
        placement=placed(),
    ).record["reference_distribution"]
    assert block["after"] == {"status": "unavailable", "reason": "disabled", "percentile": None}
    assert block["before"]["status"] == "placed"
    other = definition(tmp_path / "other", [weight(101, value="9")])
    with pytest.raises(PgsError, match="not computed from"):
        attach_reference(result, other, table=None, enabled=False)


def test_reference_matrix_audit_rejects_wrong_reports(
    tmp_path: Path, fake: MultiPlink, monkeypatch: pytest.MonkeyPatch
) -> None:
    doses = [bytes([0, 1, 2, 1]), bytes([2, 2, 0, 1])]
    kwargs: dict[str, Any] = {"root": tmp_path, "plink": fake, "stem": "synthetic"}
    good = reference_matrix_sums([1, 2], [0.5, -1.5], ["S1", "S2", "S3", "S4"], doses, **kwargs)
    assert good["sums"] == pytest.approx([-3.0, -2.5, 1.0, -1.0])
    assert good["audited_samples"] == 4 and good["audit_stride"] == 1
    strided = reference_matrix_sums(
        [1, 2], [0.5, -1.5], ["S1", "S2", "S3", "S4"], doses, audit_budget=4, **kwargs
    )
    assert strided["audit_stride"] == 2 and strided["audited_samples"] == 2
    for mode in ("wrong_sum", "wrong_samples"):
        monkeypatch.setattr(MultiPlink, "mode", mode)
        with pytest.raises(PgsError):
            reference_matrix_sums([1, 2], [0.5, -1.5], ["S1", "S2", "S3", "S4"], doses, **kwargs)
    monkeypatch.setattr(MultiPlink, "mode", "good")
    for bad in ([bytes([3, 0, 0, 0]), doses[1]], [bytes([0, 1]), doses[1]]):
        with pytest.raises(PgsError, match="Invalid reference matrix"):
            reference_matrix_sums([1, 2], [0.5, -1.5], ["S1", "S2", "S3", "S4"], bad, **kwargs)
    assert not list(tmp_path.glob("*.vcf")) and not list(tmp_path.glob("*.tsv"))


def saved_result(tmp_path: Path, fake: MultiPlink) -> tuple[Any, Path]:
    root, _ = standard(tmp_path)
    scoring, result = person(tmp_path, fake)
    attached = attach_reference(
        result,
        scoring,
        table=None,
        references_root=root,
        plink=fake,
        workspace=tmp_path / "ref",
        workers=1,
        placement=placed(),
    )
    return scoring, write_result(attached, tmp_path / "out" / "synthetic.pgs-score.json")


def test_persisted_placement_round_trips_through_api_and_cli(
    tmp_path: Path, fake: MultiPlink, monkeypatch: pytest.MonkeyPatch
) -> None:
    scoring, path = saved_result(tmp_path, fake)
    loaded = read_placement(path, scoring=scoring)
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["reference_distribution"] == stored["reference_distribution"]
    assert loaded["percentile"] == stored["percentile"]
    monkeypatch.setattr(
        Catalog,
        "default",
        lambda: Catalog(
            {"PGS000001": scoring.metadata}, scoring.metadata_source, "pgs_all_metadata_scores.csv"
        ),
    )
    cli = CliRunner().invoke(
        app, ["pgs", "placement", str(path), "--scoring-file", str(scoring.path), "--json"]
    )
    assert cli.exit_code == 0, cli.output
    assert json.loads(cli.stdout) == {"ok": True, **loaded}
    text = CliRunner().invoke(app, ["pgs", "placement", str(path)])
    assert text.exit_code == 0 and "among 20 SP1 reference samples" in text.stdout


def tamper_cases() -> dict[str, Any]:
    def reference_sum(data: dict[str, Any]) -> None:
        data["reference_distribution"]["after"]["reference_sums"][0] += 0.125

    def person_sum(data: dict[str, Any]) -> None:
        data["reference_distribution"]["after"]["person_sum"] += 0.125

    def percentile(data: dict[str, Any]) -> None:
        data["percentile"]["after"] = 50.0

    def unobserved_row(data: dict[str, Any]) -> None:
        data["reference_distribution"]["after"]["comparable_rows"].append(13)

    def group(data: dict[str, Any]) -> None:
        data["reference_distribution"]["placement"]["population"] = "PC"

    def label(data: dict[str, Any]) -> None:
        data["reference_distribution"]["sample_labels"]["super_populations"][0] = "SP2"

    def schema(data: dict[str, Any]) -> None:
        data["reference_distribution"]["schema_version"] = 2

    return {
        f.__name__: f
        for f in (reference_sum, person_sum, percentile, unobserved_row, group, label, schema)
    }


@pytest.mark.parametrize("case", sorted(tamper_cases()))
def test_tampered_placements_are_refused(tmp_path: Path, fake: MultiPlink, case: str) -> None:
    _, path = saved_result(tmp_path, fake)
    data = json.loads(path.read_text(encoding="utf-8"))
    tamper_cases()[case](data)
    path.unlink()
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(PgsError):
        read_placement(path)


def test_older_artifacts_report_no_distribution(tmp_path: Path, fake: MultiPlink) -> None:
    _, result = person(tmp_path, fake)
    data = json.loads(json.dumps(result.to_dict()))
    data["schema_version"] = 2
    data["coverage"]["score_schema_version"] = 2
    del data["reference_distribution"]
    data["percentile"] = None
    path = tmp_path / "older.pgs-score.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    loaded = read_placement(path)
    assert loaded["reference_distribution"] is None and loaded["artifact_schema_version"] == 2


def test_native_reference_matrix_arithmetic(tmp_path: Path) -> None:
    installed = os.environ.get("GENETICS_PGS_TEST_TOOLS")
    if installed is None:
        pytest.skip("set GENETICS_PGS_TEST_TOOLS for pinned native reference arithmetic")
    plink = Plink2.discover(tools_root=Path(installed))
    rng = random.Random(9404)
    samples = [f"SYN{i:04d}" for i in range(64)]
    weights = [rng.uniform(-1, 1) for _ in range(12)]
    doses = [bytes(rng.choice((0, 1, 2)) for _ in samples) for _ in weights]
    result = reference_matrix_sums(
        list(range(1, 13)), weights, samples, doses, root=tmp_path, plink=plink, stem="native"
    )
    for index, value in enumerate(result["sums"]):
        exact = math.fsum(w * row[index] for w, row in zip(weights, doses, strict=True))
        assert abs(value - exact) <= abs(exact) * 1e-5 + 1e-6
    assert result["audited_samples"] == 64


def test_cli_no_reference_is_an_explicit_recorded_opt_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from genetics.pgs import workflow

    scoring = definition(tmp_path / "def", [weight()])
    seen: dict[str, Any] = {}

    def capture(*args: Any, **kwargs: Any) -> Any:
        seen.update(kwargs)
        raise PgsError("Synthetic stop after flag capture.")

    monkeypatch.setattr(workflow, "score_export", capture)
    monkeypatch.setattr(
        Catalog,
        "default",
        lambda: Catalog(
            {"PGS000001": scoring.metadata}, scoring.metadata_source, "pgs_all_metadata_scores.csv"
        ),
    )
    for flags, expected in (([], True), (["--no-reference"], False)):
        CliRunner().invoke(
            app,
            [
                "pgs",
                "score",
                str(scoring.path),
                "--input",
                str(tmp_path / "absent.txt"),
                "--output",
                str(tmp_path / f"{expected}.pgs-score.json"),
                *flags,
            ],
        )
        assert seen["reference"] is expected


def test_review_tampered_panel_fails_before_personal_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from genetics.pgs import workflow

    root, _ = standard(tmp_path)
    vcf = root / PANEL_SOURCE / _filename("1")
    text = gzip.decompress(vcf.read_bytes()).decode()
    vcf.write_bytes(gzip.compress(text.replace("0|0", "1|1", 1).encode()))
    monkeypatch.setattr(reference, "references_dir", lambda: root)

    def untouched(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("the public panel must be verified before personal input is read")

    monkeypatch.setattr(workflow, "ingest", untouched)
    monkeypatch.setattr(workflow, "read_bundle", untouched)
    scoring = definition(tmp_path / "def", [weight(101)])
    with pytest.raises(PgsError, match="lock digest"):
        workflow.score_export(scoring, tmp_path / "absent-export.txt", no_impute=True)
    with pytest.raises(PgsError, match="lock digest"):
        workflow.score_saved(scoring, tmp_path / "absent-run")


def test_review_owned_workspace_with_person_reports_is_removed(
    tmp_path: Path, fake: MultiPlink, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path / "appdata"))
    root, _ = standard(tmp_path)
    scoring, result = person(tmp_path, fake)
    attach_reference(
        result,
        scoring,
        table=None,
        references_root=root,
        plink=fake,
        workers=1,
        placement=placed(),
    )
    pgs = tmp_path / "appdata" / "cache" / "pgs"
    assert sorted(p.name for p in pgs.iterdir()) == ["reference"]
    assert not list(pgs.rglob("*.sscore"))


def test_review_prepared_reference_must_belong_to_the_score(
    tmp_path: Path, fake: MultiPlink
) -> None:
    root, _ = standard(tmp_path)
    scoring, result = person(tmp_path, fake)
    other = definition(tmp_path / "other", [weight(101, value="3")])
    prepared = reference.prepare_reference(other, references_root=root, workers=1)
    assert isinstance(prepared, reference.PreparedReference)
    with pytest.raises(PgsError, match="different score"):
        attach_reference(
            result,
            scoring,
            table=None,
            prepared=prepared,
            plink=fake,
            workspace=tmp_path / "ref",
            placement=placed(),
        )


@pytest.mark.parametrize("case", ["claimed_unavailable", "missing_key", "phantom_percentile"])
def test_review_malformed_phase_blocks_are_categorical_refusals(
    tmp_path: Path, fake: MultiPlink, case: str
) -> None:
    root, _ = standard(tmp_path)
    scoring, result = person(tmp_path, fake, no_impute=True, dosages=None)
    attached = attach_reference(
        result,
        scoring,
        table=None,
        references_root=root,
        plink=fake,
        workspace=tmp_path / "ref",
        workers=1,
        placement=placed(),
    )
    path = write_result(attached, tmp_path / "out" / "synthetic.pgs-score.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    block = data["reference_distribution"]
    if case == "claimed_unavailable":
        block["before"] = {"status": "unavailable", "reason": "disabled", "percentile": None}
        data["percentile"]["before"] = None
    elif case == "missing_key":
        del block["before"]["person_verification"]
    else:
        block["after"]["percentile"] = 50.0
        data["percentile"]["after"] = 50.0
    path.unlink()
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(PgsError):
        read_placement(path)
