"""Citation validation (roadmap M3.1, AGENTS.md 6 "never invent a citation").

The rule under test is not "a citation exists" but "a citation is *checkable*". A card
carrying ``see Smith et al.`` passes the first and defeats the purpose of the second.
"""

from __future__ import annotations

from typing import Any

import pytest

from genetics.engine.citations import Citation, CitationError, CitationType


def _doi(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "type": "doi",
        "id": "10.1038/s41586-000-00000-0",
        "title": "A synthetic paper",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Accepted
# ---------------------------------------------------------------------------


def test_a_well_formed_doi_parses() -> None:
    citation = Citation.parse(_doi(), "c")
    assert citation.type is CitationType.DOI
    assert citation.id == "10.1038/s41586-000-00000-0"


@pytest.mark.parametrize(
    "written",
    [
        "https://doi.org/10.1038/nature12373",
        "http://doi.org/10.1038/nature12373",
        "doi:10.1038/nature12373",
        "10.1038/nature12373",
    ],
)
def test_a_doi_resolver_prefix_is_stripped_not_rejected(written: str) -> None:
    """Rejecting these would be a check that punishes a correct citation.

    The identifier is right; only the paste is decorated. An author told "malformed DOI"
    about a DOI that resolves will edit until the message goes away, which is how a good
    citation becomes a wrong one.
    """
    assert Citation.parse(_doi(id=written), "c").id == "10.1038/nature12373"


def test_a_pmid_is_a_bare_integer() -> None:
    citation = Citation.parse({"type": "pmid", "id": "23453885", "title": "x"}, "c")
    assert citation.id == "23453885"


def test_an_accession_names_its_database() -> None:
    citation = Citation.parse(
        {"type": "accession", "id": "VCV000012345", "database": "ClinVar", "title": "x"},
        "c",
    )
    assert str(citation) == "ClinVar:VCV000012345"


def test_pmcid_is_upper_cased() -> None:
    assert (
        Citation.parse({"type": "pmcid", "id": "pmc3737249", "title": "x"}, "c").id == "PMC3737249"
    )


# ---------------------------------------------------------------------------
# Refused
# ---------------------------------------------------------------------------


def test_a_bare_string_citation_is_refused() -> None:
    """The central case: prose that satisfies "has a citation" and cannot be checked."""
    with pytest.raises(CitationError) as caught:
        Citation.parse("Smith et al., 2019", "c")
    assert "mapping" in str(caught.value)


@pytest.mark.parametrize(
    "bad",
    [
        "not-a-doi",
        "10.abc/xyz",  # registrant prefix must be digits
        "10.1/x",  # too short
        "Smith 2019",
        "",
    ],
)
def test_malformed_dois_are_refused(bad: str) -> None:
    with pytest.raises(CitationError):
        Citation.parse(_doi(id=bad), "c")


@pytest.mark.parametrize("bad", ["0123", "abc", "-5", "12.5"])
def test_malformed_pmids_are_refused(bad: str) -> None:
    with pytest.raises(CitationError):
        Citation.parse({"type": "pmid", "id": bad, "title": "x"}, "c")


def test_an_accession_without_a_database_is_refused() -> None:
    """An accession alone does not say where to look it up, so it is unverifiable."""
    with pytest.raises(CitationError) as caught:
        Citation.parse({"type": "accession", "id": "VCV000012345", "title": "x"}, "c")
    assert "database" in str(caught.value)


def test_a_database_on_a_doi_is_refused() -> None:
    """The inverse. A field that applies to one type and is ignored on the others is a
    field authors will fill in wrongly and never be told about."""
    with pytest.raises(CitationError):
        Citation.parse(_doi(database="Crossref"), "c")


def test_a_missing_title_is_refused() -> None:
    """The title is what makes a fabricated reference visible in a diff."""
    with pytest.raises(CitationError) as caught:
        Citation.parse({"type": "doi", "id": "10.1038/nature12373"}, "c")
    assert "title" in str(caught.value)


def test_an_unknown_type_is_refused_and_lists_the_known_ones() -> None:
    with pytest.raises(CitationError) as caught:
        Citation.parse({"type": "isbn", "id": "x", "title": "y"}, "c")
    assert "doi" in str(caught.value)


def test_an_unexpected_key_is_refused() -> None:
    """Typo protection. A silently-ignored key looks exactly like one that had no effect."""
    with pytest.raises(CitationError) as caught:
        Citation.parse(_doi(titel="typo"), "c")
    assert "titel" in str(caught.value)


def test_a_plain_http_url_citation_is_refused() -> None:
    with pytest.raises(CitationError):
        Citation.parse({"type": "url", "id": "http://example.org/x", "title": "y"}, "c")
