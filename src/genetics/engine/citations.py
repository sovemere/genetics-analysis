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
from urllib.parse import quote


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


# ---------------------------------------------------------------------------
# Resolution (roadmap M4.6)
# ---------------------------------------------------------------------------

#: Where an accession lives, keyed by its database name reduced to letters and digits.
#:
#: Keyed on the database rather than on the identifier's shape, because accession formats
#: overlap: ``rs17822931`` and ``RCV000030373`` are both matched by the deliberately loose
#: accession pattern, and guessing the registry from the prefix would silently point a
#: PharmGKB id at dbSNP the first time a new database arrives. A database this table does
#: not name resolves to ``None`` -- shown as text, never as a link to somewhere plausible.
#:
#: ``database`` is authored free text, so it is reduced by :func:`_registry` before lookup
#: rather than matched literally. The first cut lowercased only, and then needed *two* keys
#: for the PGS Catalog to cover ``PGS Catalog`` and ``PGScatalog`` -- two names for one
#: registry, and still no entry for ``PGS-Catalog``, which would have silently rendered as
#: text with nothing to say why.
_ACCESSION_RESOLVERS: Final[dict[str, str]] = {
    "dbsnp": "https://www.ncbi.nlm.nih.gov/snp/{id}",
    "clinvar": "https://www.ncbi.nlm.nih.gov/clinvar/variation/{id}/",
    "pharmgkb": "https://www.pharmgkb.org/variant/{id}",
    "pgscatalog": "https://www.pgscatalog.org/score/{id}/",
    "omim": "https://www.omim.org/entry/{id}",
    "ensembl": "https://www.ensembl.org/id/{id}",
}

_NOT_ALPHANUMERIC: Final[re.Pattern[str]] = re.compile(r"[^a-z0-9]+")


def _registry(database: str | None) -> str:
    """A database name reduced to the key :data:`_ACCESSION_RESOLVERS` uses.

    ``PGS Catalog``, ``PGS-Catalog``, ``pgscatalog`` and ``PGS_Catalog`` are one registry
    written four ways, and a card author has no reason to prefer any of them.
    """
    return _NOT_ALPHANUMERIC.sub("", (database or "").strip().lower())


_TYPE_RESOLVERS: Final[dict[CitationType, str]] = {
    CitationType.DOI: "https://doi.org/{id}",
    CitationType.PMID: "https://pubmed.ncbi.nlm.nih.gov/{id}/",
    CitationType.PMCID: "https://www.ncbi.nlm.nih.gov/pmc/articles/{id}/",
}

#: Characters left alone when an identifier is placed into a URL path.
#:
#: Exactly the set :data:`_FORMATS` already permits in a DOI, so a well-formed identifier
#: passes through unchanged and the escaping is a second line rather than a transformation
#: nobody can predict. ``quote`` still runs, because the identifier reaching this function
#: came out of a *saved bundle* -- a file another version wrote -- and not out of the
#: schema that validated it at authoring time.
_PATH_SAFE: Final[str] = "/:;()-._~"


def citation_url(citation_type: str, identifier: str, database: str | None = None) -> str | None:
    """The public page for a citation, or ``None`` when this project will not link to it.

    Takes **strings, not a** :class:`Citation`, because its caller is the dashboard and the
    dashboard's input is a bundle: a stored citation is whatever mapping some version of
    this engine wrote, re-read without re-validation (see
    :mod:`genetics.run.bundle`). Handing that to a template and letting Jinja put it in an
    ``href`` would make the one attribute on the page that leaves the machine the one field
    nothing checks -- and for ``CitationType.URL`` the stored ``id`` *is* the whole URL, so
    a bundle carrying ``javascript:...`` there would become a clickable script.

    So every input is re-validated here, against the same :data:`_FORMATS` patterns the
    schema applies at load, and anything that does not match resolves to ``None``. A card
    whose citation will not resolve still renders -- as text, with its identifier visible --
    because AGENTS.md §0.1A's rule is that a weak thing is labelled rather than dropped,
    and that applies to a citation this reader cannot turn into a link just as much as to a
    finding it cannot score.
    """
    try:
        parsed = CitationType(str(citation_type).strip().lower())
    except ValueError:
        return None

    raw = str(identifier).strip()
    if not _FORMATS[parsed].fullmatch(raw):
        return None

    if parsed is CitationType.URL:
        # Returned verbatim rather than quoted: it is already a URL, and percent-encoding
        # one re-encodes its query string into nonsense. The pattern above has established
        # the `https://` scheme and the absence of whitespace, which is what makes putting
        # it in an `href` safe -- there is no `javascript:` form that reaches here.
        return raw

    template = _TYPE_RESOLVERS.get(parsed)
    if template is None:
        template = _ACCESSION_RESOLVERS.get(_registry(database))
        if template is None:
            return None

    return template.format(id=quote(raw, safe=_PATH_SAFE))
