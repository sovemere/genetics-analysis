"""Synthetic test fixtures (roadmap M0.2).

Every fixture here is invented from a seeded RNG. **Nothing in this module reads,
subsets, or derives from a real DNA export** -- see AGENTS.md section 1.2. That rule
exists because a fixture is the most likely way a real genotype reaches a public repo:
it looks like test data, so nobody scrutinises it.

What *is* borrowed from the real world, and why it is safe:

* Marker counts per chromosome, and the indel / no-call rates, follow the shape of the
  AncestryDNA V2 array. Those describe the **chip design** -- identical for every person
  tested on it -- and carry no individual information.
* Approximate GRCh37 chromosome lengths, so positions land in plausible ranges. Public
  reference constants.

Genotypes themselves are drawn from a seeded RNG under Hardy-Weinberg, from invented
allele frequencies. rsIDs are sequential synthetic identifiers; they are format-valid
(``rs`` + digits) so parser tests are meaningful, and any collision with a real dbSNP
entry is coincidental and carries no real genotype.

Determinism
-----------
``random.Random`` (Mersenne Twister) with a fixed seed, and each fixture derives its own
RNG from ``(seed, fixture name)``. Adding a fixture therefore cannot perturb the bytes of
the existing ones. Files are written with explicit ``\\n`` newlines and UTF-8 without BOM
so output is byte-identical on Windows and Linux -- see ``.gitattributes``, which stops
git from rewriting these to CRLF on checkout.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

GENERATOR_VERSION = 1
"""Bump when output bytes change intentionally. Fixtures must then be regenerated."""

DEFAULT_FIXTURE_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "synthetic"

DEFAULT_SEED = 20260815
DEFAULT_MARKERS = 12000

_RSID_BASE = 900_000_000
"""Synthetic rsIDs count up from here. High enough to look plausible, arbitrary."""

# Relative marker density per vendor chromosome code, following the AncestryDNA V2
# array layout. Codes: 1-22 autosomes, 23=X, 24=Y, 25=PAR, 26=MT.
_CHROM_WEIGHTS: dict[int, float] = {
    1: 0.0746,
    2: 0.0810,
    3: 0.0639,
    4: 0.0544,
    5: 0.0573,
    6: 0.0639,
    7: 0.0511,
    8: 0.0487,
    9: 0.0437,
    10: 0.0484,
    11: 0.0480,
    12: 0.0462,
    13: 0.0368,
    14: 0.0312,
    15: 0.0315,
    16: 0.0345,
    17: 0.0338,
    18: 0.0280,
    19: 0.0251,
    20: 0.0267,
    21: 0.0150,
    22: 0.0162,
    23: 0.0373,
    24: 0.0025,
    25: 0.00005,
    26: 0.0004,
}

# Approximate GRCh37 lengths (bp), used only to place positions plausibly.
_CHROM_LENGTHS: dict[int, int] = {
    1: 249_250_621,
    2: 243_199_373,
    3: 198_022_430,
    4: 191_154_276,
    5: 180_915_260,
    6: 171_115_067,
    7: 159_138_663,
    8: 146_364_022,
    9: 141_213_431,
    10: 135_534_747,
    11: 135_006_516,
    12: 133_851_895,
    13: 115_169_878,
    14: 107_349_540,
    15: 102_531_392,
    16: 90_354_753,
    17: 81_195_210,
    18: 78_077_248,
    19: 59_128_983,
    20: 63_025_520,
    21: 48_129_895,
    22: 51_304_566,
    23: 155_270_560,
    24: 59_373_566,
    25: 2_649_520,
    26: 16_569,
}

_INDEL_RATE = 0.013
"""~8,830 of 677,436 markers on the V2 array are I/D coded."""

_BASE_NOCALL_RATE = 0.0008
"""~550 of 677,436."""

_BASES = ("A", "C", "G", "T")

Sex = Literal["male", "female"]


@dataclass(frozen=True)
class FixtureSpec:
    """One generated file."""

    name: str
    description: str
    sex: Sex = "male"
    nocall_rate: float = _BASE_NOCALL_RATE
    vendor: Literal["ancestry", "23andme"] = "ancestry"
    build: str = "37"
    malformed_header: bool = False
    spike_ins: dict[str, tuple[int, int, str, str]] = field(default_factory=dict)
    """rsid -> (vendor chrom code, GRCh37 pos, allele1, allele2).

    Hook for the card engine (M3), which needs known markers with *chosen* genotypes to
    test matching. Left empty until reference data lands in M2, because populating it now
    would mean inventing GRCh37 coordinates -- wrong data is worse than no data.
    """


FIXTURES: tuple[FixtureSpec, ...] = (
    FixtureSpec(
        name="ancestry_v2_male.txt",
        description="Baseline male sample: hemizygous X written as doubled homozygote, Y called.",
        sex="male",
    ),
    FixtureSpec(
        name="ancestry_v2_female.txt",
        description="Baseline female sample: heterozygous X, Y entirely no-call.",
        sex="female",
    ),
    FixtureSpec(
        name="ancestry_v2_high_nocall.txt",
        description="Elevated no-call rate (~6%), for QC threshold tests.",
        sex="female",
        nocall_rate=0.06,
    ),
    FixtureSpec(
        name="ancestry_v2_wrong_build.txt",
        description="Declares build 38. Ingest must reject this, not silently proceed.",
        sex="male",
        build="38",
    ),
    FixtureSpec(
        name="ancestry_v2_malformed_header.txt",
        description="Truncated header, missing the column row. Ingest must fail loudly.",
        sex="male",
        malformed_header=True,
    ),
    FixtureSpec(
        name="other_vendor_23andme.txt",
        description=(
            "Different vendor layout: 4 columns with a merged genotype, letter chromosome "
            "codes. Proves the adapter seam without touching any analysis module."
        ),
        sex="male",
        vendor="23andme",
    ),
)


def _fixture_rng(seed: int, name: str) -> random.Random:
    """Derive an independent RNG per fixture, so fixtures do not perturb each other."""
    digest = hashlib.sha256(f"{seed}:{GENERATOR_VERSION}:{name}".encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _allocate_markers(total: int) -> dict[int, int]:
    """Split a marker budget across chromosomes by array density."""
    counts = {code: max(1, round(total * weight)) for code, weight in _CHROM_WEIGHTS.items()}
    return counts


def _pick_alleles(rng: random.Random) -> tuple[str, str]:
    """Choose the two possible alleles at a locus: either a SNP pair or an indel."""
    if rng.random() < _INDEL_RATE:
        return ("I", "D")
    major = rng.choice(_BASES)
    minor = rng.choice([b for b in _BASES if b != major])
    return (major, minor)


def _genotype(
    rng: random.Random,
    major: str,
    minor: str,
    *,
    diploid: bool,
) -> tuple[str, str]:
    """Draw a genotype under Hardy-Weinberg from an invented minor allele frequency.

    When ``diploid`` is False the locus is hemizygous (male X/Y, and MT), which the
    vendor format writes as a doubled homozygote -- indistinguishable from a true
    homozygote by the genotype string alone. That ambiguity is deliberate: it is exactly
    what AGENTS.md section 2 warns about, and the parser must handle it via inferred sex
    rather than by reading the string.
    """
    maf = rng.uniform(0.02, 0.5)
    if not diploid:
        allele = minor if rng.random() < maf else major
        return (allele, allele)

    roll = rng.random()
    if roll < maf * maf:
        pair = (minor, minor)
    elif roll < maf * maf + 2 * maf * (1 - maf):
        # Heterozygote. Randomise the column order on purpose: the format does not
        # guarantee an ordering, and the parser must sort rather than compare
        # positionally (AGENTS.md section 2).
        pair = (major, minor) if rng.random() < 0.5 else (minor, major)
    else:
        pair = (major, major)
    return pair


def _ancestry_header(build: str) -> list[str]:
    """Structurally faithful synthetic header.

    Deliberately *not* a copy of the vendor's prose. It keeps the machine-detectable
    tokens the parser keys on (array version, build, forward-strand declaration) and the
    same overall shape: comment block, then a tab-delimited column row.
    """
    return [
        "#AncestryDNA raw data download",
        "#SYNTHETIC TEST FIXTURE - generated data, not a real person.",
        "#This file was generated by genetics-analysis for testing purposes.",
        "#Data was collected using AncestryDNA array version: V2.0",
        "#Data is formatted using AncestryDNA converter version: V1.0",
        "#",
        "#This file mimics the structure of a consumer raw-data export so that the",
        "#ingest layer can be tested without using anyone's real genotypes.",
        "#",
        "#Genetic data is provided below as five TAB delimited columns.  Each line",
        "#corresponds to a SNP.  Column one provides the SNP identifier (rsID where",
        "#possible).  Columns two and three contain the chromosome and basepair position",
        f"#of the SNP using human reference build {build} coordinates.  Columns four and five",
        "#contain the two alleles observed at this SNP (genotype).  The genotype is reported",
        "#on the forward (+) strand with respect to the human reference.",
        "#",
        "#Chromosome codes: 1-22 autosomal, 23=X, 24=Y, 25=PAR, 26=MT",
    ]


def _render(spec: FixtureSpec, rng: random.Random, markers: int) -> str:
    counts = _allocate_markers(markers)
    lines: list[str] = []

    if spec.vendor == "ancestry":
        if spec.malformed_header:
            lines.extend(_ancestry_header(spec.build)[:4])
            # No column header row -- ingest must reject rather than guess.
        else:
            lines.extend(_ancestry_header(spec.build))
            lines.append("rsid\tchromosome\tposition\tallele1\tallele2")
    else:
        lines.extend(
            [
                "# SYNTHETIC TEST FIXTURE - generated data, not a real person.",
                "# This data file generated by a test harness, in 23andMe-like layout.",
                f"# build {spec.build}",
                "#",
                "# rsid\tchromosome\tposition\tgenotype",
            ]
        )

    rsid_counter = _RSID_BASE
    letter_chrom = {23: "X", 24: "Y", 25: "X", 26: "MT"}

    for code in sorted(counts):
        n = counts[code]
        length = _CHROM_LENGTHS[code]
        positions = sorted(rng.sample(range(1, length), min(n, length - 1)))

        for pos in positions:
            rsid_counter += 1
            rsid = f"rs{rsid_counter}"
            major, minor = _pick_alleles(rng)

            # Females have no Y: the vendor emits no-calls rather than omitting rows.
            female_y = spec.sex == "female" and code == 24
            # Hemizygous: male X and Y (but not PAR, which is diploid in both sexes),
            # and MT, which is single-copy in everyone.
            hemizygous = (spec.sex == "male" and code in (23, 24)) or code == 26

            if female_y or rng.random() < spec.nocall_rate:
                a1, a2 = "0", "0"
            else:
                a1, a2 = _genotype(rng, major, minor, diploid=not hemizygous)

            if spec.vendor == "ancestry":
                lines.append(f"{rsid}\t{code}\t{pos}\t{a1}\t{a2}")
            else:
                chrom = letter_chrom.get(code, str(code))
                genotype = "--" if a1 == "0" else f"{a1}{a2}"
                lines.append(f"{rsid}\t{chrom}\t{pos}\t{genotype}")

    for rsid, (code, pos, a1, a2) in sorted(spec.spike_ins.items()):
        if spec.vendor == "ancestry":
            lines.append(f"{rsid}\t{code}\t{pos}\t{a1}\t{a2}")
        else:
            chrom = letter_chrom.get(code, str(code))
            lines.append(f"{rsid}\t{chrom}\t{pos}\t{a1}{a2}")

    return "\n".join(lines) + "\n"


def render_fixture(
    spec: FixtureSpec,
    *,
    seed: int = DEFAULT_SEED,
    markers: int = DEFAULT_MARKERS,
) -> str:
    """Render one fixture to a string. Pure and deterministic."""
    return _render(spec, _fixture_rng(seed, spec.name), markers)


def _write(path: Path, content: str) -> None:
    """Write with explicit LF and UTF-8, so bytes match across platforms."""
    path.write_text(content, encoding="utf-8", newline="\n")


def generate_all(
    out_dir: Path | None = None,
    *,
    seed: int = DEFAULT_SEED,
    markers: int = DEFAULT_MARKERS,
) -> list[Path]:
    """Generate every fixture plus a MANIFEST.json, and return the paths written."""
    target = out_dir or DEFAULT_FIXTURE_DIR
    target.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    entries: list[dict[str, object]] = []

    for spec in FIXTURES:
        content = render_fixture(spec, seed=seed, markers=markers)
        path = target / spec.name
        _write(path, content)
        written.append(path)
        entries.append(
            {
                "name": spec.name,
                "description": spec.description,
                "sex": spec.sex,
                "vendor": spec.vendor,
                "build": spec.build,
                "rows": content.count("\n"),
                "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            }
        )

    manifest = {
        "generator_version": GENERATOR_VERSION,
        "seed": seed,
        "markers": markers,
        "note": (
            "Synthetic data generated by src/genetics/testing/fixtures.py. "
            "Contains no real genotypes. Regenerate with: genetics fixtures"
        ),
        "fixtures": entries,
    }
    manifest_path = target / "MANIFEST.json"
    _write(manifest_path, json.dumps(manifest, indent=2) + "\n")
    written.append(manifest_path)

    return written


def verify_all(
    out_dir: Path | None = None,
    *,
    seed: int = DEFAULT_SEED,
    markers: int = DEFAULT_MARKERS,
) -> list[str]:
    """Return the names of fixtures whose on-disk bytes differ from a fresh generation.

    Empty list means the committed fixtures are reproducible.
    """
    target = out_dir or DEFAULT_FIXTURE_DIR
    drifted: list[str] = []

    for spec in FIXTURES:
        path = target / spec.name
        expected = render_fixture(spec, seed=seed, markers=markers)
        if not path.exists() or path.read_text(encoding="utf-8") != expected:
            drifted.append(spec.name)

    return drifted
