"""Tests for the licence table (roadmap M2.1).

The thing worth testing is not that CC0 is permissive -- it is that the gate cannot be
talked out of a refusal, and that it refuses the *right* things. A gate that blocks
everything is as useless as one that blocks nothing, because both get bypassed.
"""

from __future__ import annotations

import pytest

from genetics.refs import licenses
from genetics.refs.licenses import Standing


def test_unknown_licence_raises_rather_than_defaulting_to_permissive() -> None:
    """The fail-closed case. An unclassified licence is the one nobody thought about."""
    with pytest.raises(licenses.UnknownLicenseError) as excinfo:
        licenses.get("MIT-but-actually-restrictive")
    # The message has to say what to do, or the next person guesses.
    assert "not assumed permissive" in str(excinfo.value)


def test_snpedia_is_restricted_and_needs_opt_in() -> None:
    """AGENTS.md 4.8 trap 2."""
    terms = licenses.get("CC-BY-NC-SA-3.0-US")
    assert terms.standing is Standing.RESTRICTED
    assert terms.needs_opt_in is True


def test_share_alike_is_restricted_even_though_commercial_use_is_allowed() -> None:
    """CC-BY-SA permits commercial use, so a naive 'is it non-commercial?' check passes it.

    It is restricted here for the other reason: a derivative knowledge-pack entry would
    carry the copyleft into a permissively-licensed repository.
    """
    terms = licenses.get("CC-BY-SA-4.0")
    assert terms.commercial_ok is True
    assert terms.share_alike is True
    assert terms.standing is Standing.RESTRICTED


def test_no_derivatives_is_restricted() -> None:
    terms = licenses.get("CC-BY-NC-ND-4.0")
    assert terms.derivative_ok is False
    assert terms.standing is Standing.RESTRICTED


def test_pgs_catalog_is_per_record_and_deliberately_not_blocked() -> None:
    """The judgement call in AGENTS.md 4.8 trap 1, made explicit.

    Most PGS Catalog scores are under the EBI default; a few dozen are not. Refusing the
    whole catalogue would block thousands of usable scores and train people to pass a
    blanket opt-in, which is how a gate stops protecting anything. The obligation belongs
    at score-selection time (M9.1), so this standing warns rather than refuses.
    """
    terms = licenses.get("LicenseRef-PGS-Catalog-Per-Score")
    assert terms.authoritative is False
    assert terms.standing is Standing.PER_RECORD
    assert terms.needs_opt_in is False


def test_omim_forbids_derivatives() -> None:
    """AGENTS.md 4.8 trap 3."""
    terms = licenses.get("LicenseRef-OMIM-No-Derivatives")
    assert terms.derivative_ok is False
    assert terms.redistribution_ok is False
    assert terms.needs_opt_in is True


def test_a_clean_confirmed_licence_is_permissive() -> None:
    assert licenses.get("CC0-1.0").standing is Standing.PERMISSIVE
    assert licenses.get("CC-BY-4.0").standing is Standing.PERMISSIVE


def test_unconfirmed_classification_does_not_read_as_permissive() -> None:
    """An entry nobody has checked must not be indistinguishable from a checked one.

    This is what keeps the M15.4 audit from being a vague instruction to 'review the
    licences' -- the ones still to review name themselves.
    """
    unreviewed = [t for t in licenses.LICENSES.values() if t.review_status != "confirmed"]
    assert unreviewed, "expected some entries to be honestly marked as unreviewed"
    for terms in unreviewed:
        if terms.authoritative and not terms.needs_opt_in:
            assert terms.standing is Standing.NEEDS_REVIEW


def test_every_licence_records_where_its_terms_are_published() -> None:
    """Without this the audit has nothing to audit against."""
    for license_id, terms in licenses.LICENSES.items():
        assert terms.terms_url.startswith("https://"), license_id
        assert terms.id == license_id


def test_non_spdx_ids_use_the_licenseref_convention() -> None:
    """So a reader can tell at a glance which ids are standard and which we coined."""
    spdx_like = {
        "CC0-1.0",
        "CC-BY-4.0",
        "CC-BY-SA-4.0",
        "CC-BY-NC-SA-3.0-US",
        "CC-BY-NC-ND-4.0",
    }
    for license_id in licenses.LICENSES:
        if license_id not in spdx_like:
            assert license_id.startswith("LicenseRef-"), license_id
