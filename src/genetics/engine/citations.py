"""Citation records, validated by shape (roadmap M3.1, AGENTS.md 6).

AGENTS.md is unambiguous: *never invent a citation*, and *a card without a citation does
not render*. The roadmap turns that into a schema rule -- ``citations`` is required and a
card lacking one cannot ship.

**That rule is not enough on its own, which is the point of this module.** A free-text
citation field satisfies "has a citation" while carrying ``"see Smith et al., 2019"``,
which is precisely the fabrication the rule exists to prevent: it is unresolvable, so
nobody can check it, so nobody does. A citation here is therefore *structured* -- a type
and an identifier in that type's format -- so "this card is cited" becomes a claim that
can be mechanically checked rather than merely asserted.

The formats below reject a malformed identifier at load. They cannot tell whether the
identifier resolves to a real record; that needs the network, and this pipeline is
offline. Resolution is M15.6's audit. What load-time validation buys is that the *shape*
is right, which is what separates a mistyped DOI from an invented one: an invented DOI
usually is not a DOI at all.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final


class CitationError(ValueError):
    """Raised for a citation that is absent, malformed, or of an unknown type."""


class CitationType(StrEnum):
    DOI = "doi"
    PMID = "pmid"
    PMCID = "pmcid"
    ACCESSION = "accession"
    """A database record: ClinVar RCV/VCV, dbSNP rs, PharmGKB, PGS Catalog. Named by the
    database it belongs to via :attr:`Citation.database`, since the identifier alone does
    not say where to look it up."""

    URL = "url"
    """Last resort, for a primary source with no persistent identifier -- a CPIC guideline
    table, a consortium data release. Deliberately awkward relative to the others, because
    a URL is the one citation form that rots."""


_FORMATS: Final[dict[CitationType, re.Pattern[str]]] = {
    # Crossref's own recommended pattern. The registrant prefix is always 10.NNNN.
    CitationType.DOI: re.compile(r"^10\.\d{4,9}/[-._;()/:a-zA-Z0-9]+$"),
    # PubMed ids are bare integers and are never zero-padded.
    CitationType.PMID: re.compile(r"^[1-9]\d{0,8}$"),
    CitationType.PMCID: re.compile(r"^PMC\d{1,9}$"),
    # Deliberately loose: accession formats vary per database and pinning each one here
    # would mean guessing at databases not yet used. It still rejects prose, which is the
    # failure being guarded.
    CitationType.ACCESSION: re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{2,63}$"),
    CitationType.URL: re.compile(r"^https://[^\s]+$"),
}

_REQUIRES_DATABASE: Final[frozenset[CitationType]] = frozenset({CitationType.ACCESSION})

_ALLOWED_KEYS: Final[frozenset[str]] = frozenset({"type", "id", "title", "database", "note"})


@dataclass(frozen=True)
class Citation:
    """One resolvable reference."""

    type: CitationType
    id: str
    title: str
    """Required, and not redundant with the identifier. A reviewer scanning a card diff
    reads titles, not DOIs, and a title that does not match its DOI is the single most
    visible sign of a fabricated or copy-pasted reference -- which is the failure AGENTS.md
    6 and M15.6 are both aimed at. It costs one line and makes the corpus reviewable."""

    database: str | None = None
    """Which database an ``accession`` belongs to. Required for that type only."""

    note: str | None = None
    """Optional scope marker: which table, which figure, which cohort."""

    def __str__(self) -> str:
        if self.type is CitationType.ACCESSION and self.database:
            return f"{self.database}:{self.id}"
        return f"{self.type.value}:{self.id}"

    @classmethod
    def parse(cls, raw: Any, where: str) -> Citation:
        if not isinstance(raw, Mapping):
            raise CitationError(
                f"{where}: each citation must be a mapping with 'type', 'id' and 'title', "
                f"got {type(raw).__name__}. A bare string is not accepted -- see the module "
                "docstring for why an unstructured citation is the failure, not the fix."
            )

        unexpected = sorted(set(raw) - _ALLOWED_KEYS)
        if unexpected:
            raise CitationError(
                f"{where}: unexpected key(s) {', '.join(unexpected)}. "
                f"Accepted: {', '.join(sorted(_ALLOWED_KEYS))}."
            )

        for key in ("type", "id", "title"):
            if not str(raw.get(key) or "").strip():
                raise CitationError(f"{where}: missing required key {key!r}")

        type_text = str(raw["type"]).strip().lower()
        try:
            citation_type = CitationType(type_text)
        except ValueError:
            known = ", ".join(t.value for t in CitationType)
            raise CitationError(
                f"{where}: unknown citation type {type_text!r}. Known: {known}."
            ) from None

        identifier = str(raw["id"]).strip()
        # DOIs are widely pasted with a resolver prefix. Strip it rather than reject: the
        # citation is correct and the author would otherwise "fix" it by guessing.
        if citation_type is CitationType.DOI:
            for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
                if identifier.lower().startswith(prefix):
                    identifier = identifier[len(prefix) :]
                    break
        if citation_type is CitationType.PMCID:
            identifier = identifier.upper()

        if not _FORMATS[citation_type].fullmatch(identifier):
            raise CitationError(
                f"{where}: {identifier!r} is not a well-formed {citation_type.value}. "
                f"Expected {_FORMATS[citation_type].pattern}."
            )

        database = str(raw["database"]).strip() if raw.get("database") else None
        if citation_type in _REQUIRES_DATABASE and not database:
            raise CitationError(
                f"{where}: an accession needs 'database' -- the identifier alone does not "
                "say where to look it up, which makes it unverifiable."
            )
        if database and citation_type not in _REQUIRES_DATABASE:
            raise CitationError(
                f"{where}: 'database' applies to accessions only, not to {citation_type.value}."
            )

        return cls(
            type=citation_type,
            id=identifier,
            title=str(raw["title"]).strip(),
            database=database,
            note=str(raw["note"]).strip() if raw.get("note") else None,
        )
