"""M9.5 study-to-sample ancestry portability for every PGS result (AGENTS.md 4.4).

A polygenic score's effect sizes were estimated in a study population and lose accuracy
in other ancestries. This module states, per score, how much of that study population is
*demonstrably* in the sample's ancestry category, and turns it into the numeric
``ancestry_match`` that :func:`~genetics.engine.confidence.calculate_confidence` accepts.
It labels; it never filters a score, a sum or a percentile.

**Both mappings are cited, not written from memory** (AGENTS.md 6):

* Sample side: the sample's 1000 Genomes population (M9.4's placement) to a Morales et al.
  2018 category. Table 1 of that paper assigns all 26 phase 3 populations by name -- e.g.
  ``KHV`` is *South East Asian*, not East Asian, and ``ACB``/``ASW`` are *African American
  or Afro-Caribbean*, not Sub-Saharan African. 1000 Genomes super-populations are not
  used for the mapping, because the paper's categories cut across them.
* Study side: the PGS Catalog publishes ancestry distributions in its *display*
  categories, which merge Morales categories (African American, African unspecified and
  Sub-Saharan African are all "African"). The catalog's own table maps one onto the other.
  A match is therefore made at display-category resolution, and the merged Morales
  categories are recorded so the merge is never invisible.

Categories with no 1000 Genomes population -- Greater Middle Eastern, Native American,
Oceanian, Central Asian -- are never mapped to a nearest population. A study share in one
of them is a mismatch for a sample placed in a 1000 Genomes population, and a sample the
panels cannot place is ``declined``.

**The number is a demonstrated lower bound.** ``Not Reported``, multi-ancestry shares
whose split is unknown, empty stages and unrecognised labels are kept as an explicit
``indeterminate`` share and never renormalised away; they count toward the upper bound
only. The driving stage is the GWAS source of variant associations, where effect sizes
were estimated; score development/training drives only when the GWAS column is empty.
Evaluation is recorded, never driving: the catalog weights it by sample sets, not people.

Sample states: ``placed`` computes a match; ``declined`` by either AADR (M5.9) or 1000
Genomes is a finding that the sample is unrepresented and sets the match to 0, never the
neutral ``None``; an AADR decline cannot be rescued by a coarser 1000 Genomes placement.
``not_run`` and ``saved_only`` (no original array to place) stay ``None`` -- unknown.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final, NoReturn

from genetics.engine.confidence import ancestry_ceiling
from genetics.pgs.catalog import PgsError

SCHEMA_VERSION: Final = 1
METHOD_VERSION: Final = 1
CORRUPT: Final = "Saved portability record is malformed or inconsistent; refused."

STAGE_COLUMNS: Final[dict[str, str]] = {
    "gwas": "Ancestry Distribution (%) - Source of Variant Associations (GWAS)",
    "development": "Ancestry Distribution (%) - Score Development/Training",
    "evaluation": "Ancestry Distribution (%) - PGS Evaluation",
}
DRIVING_ORDER: Final = ("gwas", "development")
TOTAL_TOLERANCE_PERCENT: Final = 1.0
"""Published percentages are rounded to one decimal; 6,991 scores total 99.7-100.2."""

SOURCES: Final[dict[str, Any]] = {
    "sample_mapping": {
        "citation": (
            "Morales J et al. A standardized framework for representation of ancestry data "
            "in genomics studies, with application to the NHGRI-EBI GWAS Catalog. "
            "Genome Biology 19, 21 (2018)"
        ),
        "doi": "10.1186/s13059-018-1396-2",
        "table": "Table 1",
        "verified": "2026-10-09 against the Europe PMC full text (PMC5815218)",
    },
    "display_mapping": {
        "citation": "PGS Catalog documentation: Ancestry categories",
        "url": "https://www.pgscatalog.org/docs/ancestry/",
        "verified": "2026-10-09",
    },
    "study_distributions": (
        "pgs_all_metadata_scores.csv ancestry distribution columns, "
        "as recorded in score_definition.metadata"
    ),
}

THOUSAND_GENOMES_CATEGORY: Final[dict[str, str]] = {
    # Morales et al. 2018, Table 1: "individuals who genetically cluster with reference
    # populations from this region, for example, 1000 Genomes and/or HapMap ...".
    "ACB": "African American or Afro-Caribbean",
    "ASW": "African American or Afro-Caribbean",
    "CDX": "East Asian",
    "CHB": "East Asian",
    "CHS": "East Asian",
    "JPT": "East Asian",
    "CEU": "European",
    "FIN": "European",
    "GBR": "European",
    "IBS": "European",
    "TSI": "European",
    "CLM": "Hispanic or Latin American",
    "MXL": "Hispanic or Latin American",
    "PEL": "Hispanic or Latin American",
    "PUR": "Hispanic or Latin American",
    "BEB": "South Asian",
    "GIH": "South Asian",
    "ITU": "South Asian",
    "PJL": "South Asian",
    "STU": "South Asian",
    "KHV": "South East Asian",
    "ESN": "Sub-Saharan African",
    "GWD": "Sub-Saharan African",
    "LWK": "Sub-Saharan African",
    "MSL": "Sub-Saharan African",
    "YRI": "Sub-Saharan African",
}

DISPLAY_CATEGORY: Final[dict[str, str]] = {
    # PGS Catalog "Ancestry categories": ancestry category -> display category, with the
    # display names as the metadata CSV spells them.
    "Aboriginal Australian": "Additional Diverse Ancestries",
    "African American or Afro-Caribbean": "African",
    "African unspecified": "African",
    "Asian unspecified": "Additional Asian Ancestries",
    "Central Asian": "Additional Asian Ancestries",
    "East Asian": "East Asian",
    "European": "European",
    "Greater Middle Eastern (Middle Eastern, North African, or Persian)": (
        "Greater Middle Eastern"
    ),
    "Hispanic or Latin American": "Hispanic or Latin American",
    "Native American": "Additional Diverse Ancestries",
    "Oceanian": "Additional Diverse Ancestries",
    "Other": "Additional Diverse Ancestries",
    "Other admixed ancestry": "Additional Diverse Ancestries",
    "South Asian": "South Asian",
    "South East Asian": "Additional Asian Ancestries",
    "Sub-Saharan African": "African",
}

NOT_REPORTED: Final = "Not Reported"
MULTI_INCLUDING_EUROPEAN: Final = "Multi-ancestry (including European)"
MULTI_EXCLUDING_EUROPEAN: Final = "Multi-ancestry (excluding European)"
EUROPEAN: Final = "European"
_KINDS: Final[dict[str, str]] = {
    **{label: "category" for label in sorted(set(DISPLAY_CATEGORY.values()))},
    NOT_REPORTED: "not_reported",
    MULTI_INCLUDING_EUROPEAN: "multi_including_european",
    MULTI_EXCLUDING_EUROPEAN: "multi_excluding_european",
}


def _round(value: float) -> float:
    return round(value, 6) + 0.0


def merged_categories(display: str) -> list[str]:
    """The Morales categories the catalog folds into one display category."""
    return sorted(k for k, v in DISPLAY_CATEGORY.items() if v == display)


def parse_distribution(raw: str | None) -> dict[str, Any]:
    """One stage's ``Label:percent|...`` text, with every share kept.

    Absent columns, empty text and unparseable text are explicit statuses; their whole
    share is indeterminate downstream, never dropped.
    """
    if raw is None:
        return {"status": "column_absent", "raw": None, "total_percent": None, "shares": []}
    text = raw.strip()
    if not text:
        return {"status": "empty", "raw": raw, "total_percent": None, "shares": []}
    parsed: list[tuple[str, float]] = []
    for part in text.split("|"):
        label, _, number = part.rpartition(":")
        try:
            percent = float(number)
        except ValueError:
            percent = math.nan
        # A zero share is published rounding (PGS004230 lists Not Reported:0), not an error.
        if not label.strip() or not math.isfinite(percent) or not 0 <= percent <= 100:
            return {"status": "malformed", "raw": raw, "total_percent": None, "shares": []}
        parsed.append((label.strip(), percent))
    total = math.fsum(p for _, p in parsed)
    if (
        len({label for label, _ in parsed}) != len(parsed)
        or abs(total - 100) > TOTAL_TOLERANCE_PERCENT
    ):
        return {"status": "malformed", "raw": raw, "total_percent": _round(total), "shares": []}
    return {
        "status": "reported",
        "raw": raw,
        "total_percent": _round(total),
        "shares": [
            {
                "label": label,
                "kind": _KINDS.get(label, "unrecognised"),
                "percent": percent,
                # Divides out rounding only; unknown shares stay in the denominator.
                "fraction": _round(percent / total),
            }
            for label, percent in parsed
        ],
    }


def _relation(share: Mapping[str, Any], display: str) -> str:
    kind = share["kind"]
    if kind == "category":
        return "matched" if share["label"] == display else "mismatched"
    if kind == "multi_excluding_european" and display == EUROPEAN:
        return "mismatched"
    return "indeterminate"


def stage_match(stage: Mapping[str, Any], display: str) -> dict[str, Any]:
    """Matched, mismatched and indeterminate shares of one stage for one category."""
    if stage["status"] != "reported":
        return {"matched": 0.0, "mismatched": 0.0, "indeterminate": 1.0, "per_label": []}
    totals = {"matched": 0.0, "mismatched": 0.0, "indeterminate": 0.0}
    per_label = []
    for share in stage["shares"]:
        relation = _relation(share, display)
        totals[relation] += share["fraction"]
        per_label.append({"label": share["label"], "relation": relation})
    matched, mismatched = _round(totals["matched"]), _round(totals["mismatched"])
    return {
        "matched": matched,
        "mismatched": mismatched,
        "indeterminate": _round(max(0.0, 1.0 - matched - mismatched)),
        "per_label": per_label,
    }


def _judgment(match: Mapping[str, Any]) -> str:
    if match["matched"] >= 1.0:
        return "matched"
    if match["matched"] > 0:
        return "partial"
    if match["mismatched"] >= 1.0:
        return "mismatched"
    return "not_demonstrated"


def _study(record: Mapping[str, Any]) -> dict[str, Any]:
    rows = record["score_definition"]["metadata"]["metadata_rows"]
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], Mapping):
        raise PgsError("Portability needs exactly one authoritative metadata row.")
    stages = {
        name: {"column": column, **parse_distribution(rows[0].get(column))}
        for name, column in STAGE_COLUMNS.items()
    }
    driving = next((s for s in DRIVING_ORDER if stages[s]["status"] == "reported"), None)
    reason = (
        "GWAS source of variant associations: where effect sizes were estimated."
        if driving == "gwas"
        else "No reported GWAS-source ancestry; score development/training drives."
        if driving == "development"
        else "Neither the GWAS source nor development/training reports ancestry; the "
        "whole study population is indeterminate."
    )
    return {"stages": stages, "driving_stage": driving, "driving_reason": reason}


def _aadr(record: Mapping[str, Any]) -> dict[str, Any]:
    ancestry = record.get("ancestry")
    if ancestry is None:
        return {"status": "not_supplied", "reason": "No AADR ancestry context was supplied."}
    population = ancestry["population"]
    status = population["status"]
    if status not in {"placed", "declined", "not_run"}:
        raise PgsError("Unknown AADR placement status; portability refused.")
    return {"status": status, "reason": population.get("reason") or None}


def _thousand_genomes(record: Mapping[str, Any]) -> dict[str, Any]:
    block = record.get("reference_distribution")
    if not isinstance(block, Mapping) or block.get("status") != "computed":
        status = "absent" if not isinstance(block, Mapping) else block.get("status")
        return {
            "status": "not_run",
            "reason": f"No 1000 Genomes placement: reference distribution {status}.",
            "basis": f"reference_{status}",
        }
    placement = block["placement"]
    status = placement["status"]
    if status not in {"placed", "declined", "not_run"}:
        raise PgsError("Unknown 1000 Genomes placement status; portability refused.")
    out: dict[str, Any] = {
        "status": status,
        "reason": placement.get("reason") or None,
        "basis": "reference_distribution",
    }
    if status != "placed":
        return out
    population = placement["population"]
    out["population"] = population
    out["super_population"] = placement.get("region")
    fits = placement.get("fits")
    threshold = placement.get("decline_threshold")
    if isinstance(fits, list) and isinstance(threshold, int | float):
        admissible = sorted(
            {
                str(f["population"])
                for f in fits
                if isinstance(f.get("fit"), int | float) and f["fit"] <= threshold
            }
            - {population}
        )
        out["admissible_alternatives"] = admissible
    else:
        out["admissible_alternatives"] = None
    return out


def _category(population: str) -> dict[str, Any]:
    morales = THOUSAND_GENOMES_CATEGORY.get(population)
    display = None if morales is None else DISPLAY_CATEGORY[morales]
    return {
        "population": population,
        "morales_category": morales,
        "display_category": display,
    }


def compute_portability(record: Mapping[str, Any]) -> dict[str, Any]:
    """Derive the versioned portability block from a score record's own inputs."""
    try:
        return _compute(record)
    except PgsError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise PgsError("Score record lacks valid portability inputs; refused.") from exc


def _compute(record: Mapping[str, Any]) -> dict[str, Any]:
    study = _study(record)
    aadr = _aadr(record)
    tg = _thousand_genomes(record)
    saved_only = record["original_table_sha256"] is None
    declined_by = [
        name
        for name, panel in (("aadr", aadr), ("thousand_genomes", tg))
        if panel["status"] == "declined"
    ]
    sample: dict[str, Any] = {"aadr": aadr, "thousand_genomes": tg, "declined_by": declined_by}
    stage_matches: dict[str, Any] = {}
    match: dict[str, Any] | None = None
    if declined_by:
        sample["state"] = "declined"
        ancestry_match: float | None = 0.0
        judgment = "sample_unrepresented"
        reason = (
            "The sample fits no population of the "
            + " or ".join("AADR" if d == "aadr" else "1000 Genomes" for d in declined_by)
            + " panel, so no study category can be shown to contain it; a coarser placement "
            "does not rescue a decline."
        )
    elif tg["status"] == "placed":
        category = _category(tg["population"])
        sample.update(state="placed", **category)
        display = category["display_category"]
        if display is None:
            sample["state"] = "placed_unmapped"
            ancestry_match, judgment = None, "not_computed"
            reason = "The placed population has no category in the cited mapping."
        else:
            sample["merged_morales_categories"] = merged_categories(display)
            alternatives = tg.get("admissible_alternatives")
            sample["alternative_display_categories"] = (
                None
                if alternatives is None
                else sorted(
                    {
                        str(_category(p)["display_category"])
                        for p in alternatives
                        if _category(p)["display_category"] not in {None, display}
                    }
                )
            )
            stage_matches = {
                name: stage_match(stage, display) for name, stage in study["stages"].items()
            }
            driving = study["driving_stage"]
            match = (
                stage_matches[driving]
                if driving is not None
                else {"matched": 0.0, "mismatched": 0.0, "indeterminate": 1.0, "per_label": []}
            )
            ancestry_match = match["matched"]
            judgment = _judgment(match)
            reason = (
                f"{match['matched']:.1%} of the driving study population is demonstrably "
                f"{display}; {match['indeterminate']:.1%} is indeterminate and "
                f"{match['mismatched']:.1%} is another category."
            )
    elif saved_only:
        sample["state"] = "saved_only"
        ancestry_match, judgment = None, "not_computed"
        reason = (
            "Saved-run scoring has no original array to place among 1000 Genomes "
            "populations; portability is unknown, and the pooled distribution is not matched."
        )
    else:
        sample["state"] = "not_run"
        ancestry_match, judgment = None, "not_computed"
        reason = f"The sample's study category is unknown: {tg['reason']}"
    ceiling = ancestry_ceiling(ancestry_match)
    return {
        "schema_version": SCHEMA_VERSION,
        "method_version": METHOD_VERSION,
        "method": (
            "Share of the driving study stage demonstrably in the sample's PGS Catalog "
            "display category; indeterminate shares count toward the upper bound only"
        ),
        "sources": SOURCES,
        "study": study,
        "sample": sample,
        "stage_matches": stage_matches,
        "match": None
        if match is None
        else {
            "matched": match["matched"],
            "indeterminate": match["indeterminate"],
            "mismatched": match["mismatched"],
            "upper_bound": _round(match["matched"] + match["indeterminate"]),
        },
        "ancestry_match": ancestry_match,
        "judgment": judgment,
        "confidence_ceiling": None if ceiling is None else ceiling.value,
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# Reload validation
# ---------------------------------------------------------------------------


def _fail() -> NoReturn:
    raise PgsError(CORRUPT)


def read_portability(path: Path, *, scoring: Any = None) -> dict[str, Any]:
    """Reload a private score result and return its revalidated portability.

    Schema 4 results must equal a recomputation from their own inputs. Older results
    predate the block and are recomputed from what they carry, labelled as such.
    """
    from genetics.pgs.reference import read_placement

    placement = read_placement(path, scoring=scoring)
    raw = json.loads(path.read_text(encoding="utf-8"))
    computed = json.loads(json.dumps(compute_portability(raw), allow_nan=False))
    schema = placement["artifact_schema_version"]
    if schema >= 4:
        if raw.get("portability") != computed:
            _fail()
        origin = "persisted_verified"
    else:
        if not isinstance(raw.get("portability"), str):
            _fail()
        origin = "recomputed_legacy"
    return {
        "pgs_id": placement["pgs_id"],
        "artifact_schema_version": schema,
        "scoring_source_verified": placement["scoring_source_verified"],
        "portability_origin": origin,
        "portability": computed,
    }


def summary(portability: Mapping[str, Any]) -> list[str]:
    """Plain-text lines for local terminal output; no marker identities."""
    ceiling = portability["confidence_ceiling"]
    value = portability["ancestry_match"]
    lines = [
        f"Ancestry portability: {portability['judgment']}; ancestry_match "
        + ("not computed" if value is None else f"{value:.3f}")
        + ("" if ceiling is None else f"; confidence capped at {ceiling}")
        + ".",
        f"  {portability['reason']}",
    ]
    driving = portability["study"]["driving_stage"]
    lines.append(f"  Driving study stage: {driving or 'none reported'}.")
    sample = portability["sample"]
    alternatives: Sequence[str] | None = sample.get("alternative_display_categories")
    if alternatives:
        lines.append(f"  Other admissible categories for this sample: {', '.join(alternatives)}.")
    return lines
