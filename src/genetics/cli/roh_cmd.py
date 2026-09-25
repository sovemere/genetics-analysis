"""CLI adapter for the shared M6.1 engine. Results are always JSON."""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Annotated

import typer


def _write_result(output: Path, text: str) -> None:
    """Publish complete JSON without replacing a concurrent writer's result."""
    from genetics.paths import is_inside_repo

    output = output.resolve()
    if is_inside_repo(output) or not output.name.endswith(".roh.json"):
        raise ValueError("output must be outside the repository and end in .roh.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output.parent,
            prefix=".roh-pending-",
            suffix=".roh.json",
            delete=False,
        ) as stream:
            staging = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        # Both names are on the same filesystem. link() is atomic and fails if the
        # destination exists, unlike POSIX rename(), which would overwrite it.
        os.link(staging, output)
    finally:
        if staging is not None:
            staging.unlink(missing_ok=True)


def roh(
    input_path: Annotated[Path, typer.Option("--input", exists=True, dir_okay=False)],
    reference: Annotated[
        list[Path] | None,
        typer.Option(
            "--reference", help="Unpruned GRCh37 cohort VCF or pgen; repeat per chromosome."
        ),
    ] = None,
    reference_version: Annotated[str | None, typer.Option("--reference-version")] = None,
    population: Annotated[str | None, typer.Option("--population")] = None,
    keep: Annotated[Path | None, typer.Option("--keep", exists=True, dir_okay=False)] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Save outside the repo; suffix must be .roh.json."),
    ] = None,
    settings_file: Annotated[
        Path | None,
        typer.Option("--settings", help="JSON RohSettings overrides; recorded in output."),
    ] = None,
) -> None:
    """Compute long autosomal ROH using the existing 1000G panel or an explicit cohort."""
    from genetics.external.pgen import EmptyHarmonizationError
    from genetics.external.plink2 import Plink2, Plink2Error
    from genetics.external.plink19 import Plink19
    from genetics.ingest import IngestError, ingest
    from genetics.paths import is_inside_repo, references_dir
    from genetics.structure.roh import ReferenceInput, RohSettings, compute_roh

    try:
        if output is not None:
            output = output.resolve()
        if output and (is_inside_repo(output.resolve()) or not output.name.endswith(".roh.json")):
            raise ValueError("output must be outside the repository and end in .roh.json")
        if output and output.exists():
            raise ValueError("output already exists; choose a new result path")
        if reference:
            if not reference_version or not population:
                raise ValueError("custom references require --reference-version and --population")
        else:
            if population and not keep:
                raise ValueError("--population requires --keep when using the default pooled panel")
            root = references_dir() / "thousand_genomes_phase3_grch37"
            reference = [
                root
                / f"ALL.chr{c}.phase3_shapeit2_mvncall_integrated_v5b.20130502.genotypes.vcf.gz"
                for c in range(1, 23)
            ]
            reference_version = "1000 Genomes phase 3 GRCh37 20130502 v5b"
            if keep and not population:
                raise ValueError("--keep requires an explicit --population label")
            population = population or "pooled 1000G phase 3 (not ancestry-matched)"
        refs = [ReferenceInput(p, reference_version, population, keep) for p in reference]
        settings = (
            RohSettings(**json.loads(settings_file.read_text(encoding="utf-8")))
            if settings_file
            else RohSettings()
        )
        tool2, tool19 = Plink2.discover(), Plink19.discover()
        result = compute_roh(
            ingest(input_path).table,
            refs,
            plink2=tool2,
            plink19=tool19,
            settings=settings,
            progress=lambda message: typer.echo(message, err=True),
        )
        text = json.dumps(result.as_dict(), indent=2, allow_nan=False) + "\n"
        if output:
            _write_result(output, text)
        else:
            typer.echo(text, nl=False)
    except (
        ValueError,
        OSError,
        Plink2Error,
        TypeError,
        EmptyHarmonizationError,
        IngestError,
    ) as exc:
        from genetics.privacy import redact

        typer.echo(f"ROH failed: {redact(str(exc))}", err=True)
        raise typer.Exit(1) from None
