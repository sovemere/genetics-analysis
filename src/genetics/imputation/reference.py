"""Source-bound prepared catalogs and streaming bref3 marker discovery."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from genetics.external.beagle import _CREATION_FLAGS, _java_env, _stop
from genetics.paths import references_dir
from genetics.refs.imputation import BrefTools, VcfSummary, _vcf_stream, validate_catalog
from genetics.refs.postprocess import ProcessError, declared_artifact_provenance

from .reference_stream import ReferenceStream
from .target import ImputationError


class ReferenceMarkers(dict[int, tuple[str, str] | None]):
    """Requested allele definitions and duplicates found in the verified full panel."""

    def __init__(self) -> None:
        super().__init__()
        self.duplicates: dict[tuple[int, str, str], int] = {}
        self.stream = ReferenceStream()


@dataclass(frozen=True)
class PreparedReference:
    panel_catalog: Path
    map_catalog: Path
    panel_expected: Mapping[str, Any] | None = None
    map_expected: Mapping[str, Any] | None = None

    @classmethod
    def default(cls) -> PreparedReference:
        root = references_dir()
        return cls(
            root / "thousand_genomes_phase3_grch37/bref3/panel.bref3.json",
            root / "hapmap_genetic_maps_grch37/maps/index.bref3.json",
            declared_artifact_provenance("thousand_genomes_phase3_grch37", "convert_to_bref3"),
            declared_artifact_provenance("hapmap_genetic_maps_grch37", "prepare_genetic_maps"),
        )

    def validate(self) -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            panel = validate_catalog(self.panel_catalog, expected=self.panel_expected)
            maps = validate_catalog(self.map_catalog, expected=self.map_expected)
        except ProcessError:
            raise ImputationError(
                "Prepared panels/maps are missing, damaged or stale; run refs fetch/verify."
            ) from None
        if panel["kind"] != "bref3_panel" or maps["kind"] != "genetic_maps":
            raise ImputationError("Prepared reference catalogs have the wrong roles.")
        return panel, maps


def read_markers(
    tools: BrefTools,
    panel: Path,
    chrom: str,
    expected: VcfSummary,
    wanted: set[int],
    log: Path,
    memory_mb: int,
    progress: Callable[[str], None],
    native_sink: Callable[[bytes], Any] | None = None,
) -> ReferenceMarkers:
    """Decode the full panel; buffer phased records at only one coordinate.

    Retain requested allele definitions and verified duplicate metadata, never a
    genome-wide Python GT matrix. No source VCF is needed or reference GT logged.
    Duplicate positions are declined as typed anchors; every distinct reference
    observation remains available to Beagle's full-panel imputation.
    """
    sites = ReferenceMarkers()
    sites.stream = ReferenceStream(native_sink)

    def consume(raw: bytes) -> None:
        sites.stream.consume(raw)
        if raw.startswith(b"#"):
            return
        fields = raw.split(b"\t", 5)
        pos = int(fields[1])
        ref, alt = fields[3].decode("ascii"), fields[4].decode("ascii")
        pair = (ref, alt)
        if pos in wanted:
            sites[pos] = None if pos in sites else pair

    process: subprocess.Popen[bytes] | None = None
    with log.open("wb") as diagnostics:
        try:
            progress("Reading full imputation reference markers")
            process = subprocess.Popen(
                [str(tools.java.path), f"-Xmx{memory_mb}m", "-jar", str(tools.decoder), str(panel)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=diagnostics,
                env=_java_env(),
                creationflags=_CREATION_FLAGS,
            )
            assert process.stdout is not None
            observed = _vcf_stream(
                process.stdout,
                chrom,
                consume=consume,
                progress=lambda _: progress("Reading full imputation reference markers"),
            )
            process.stdout.close()
            if process.wait() != 0 or (
                observed.records != expected.records
                or observed.samples != expected.samples
                or observed.sample_order_sha256 != expected.sample_order_sha256
                or observed.semantic_sha256 != expected.semantic_sha256
            ):
                raise ImputationError("Decoded reference no longer matches its prepared summary.")
        except (OSError, ValueError, UnicodeError, ProcessError) as exc:
            if isinstance(exc, ImputationError):
                raise
            raise ImputationError(
                "Full-reference marker decoding failed; inspect private logs."
            ) from None
        finally:
            if process is not None:
                _stop(process)
                if process.stdout is not None:
                    process.stdout.close()
    sites.stream.summary()
    sites.duplicates = sites.stream.duplicates
    return sites
