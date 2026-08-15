"""What each reference licence permits (roadmap M2.1, M2.2).

**The manifest names a licence; it never describes one.** That split is the entire point
of this module and the reason the table lives in code rather than in the YAML.

A manifest entry that could declare its own ``permissive: true`` would put the licence
gate under the control of the person adding a source -- which is precisely the person
motivated to get past it. The gate would then be defeated by a typo, by an optimistic
reading of a terms page, or by a copy-paste from the entry above. Here, a source declares
``license: CC-BY-NC-SA-3.0-US`` and the properties are looked up. Getting a
non-commercial source past :func:`standing` requires editing this file, which is a diff a
reviewer will actually read.

Fail closed
-----------
An id absent from :data:`LICENSES` raises. It does not default to permissive, and it does
not default to restricted-but-fetchable-with-a-warning. This is the M0/M1 lesson applied
to licensing: a guard whose failure mode is "carry on" is not a guard. A new source with
an unfamiliar licence stops the manifest from loading at all, and the fix is to read the
terms and add an entry.

Honesty about our own confidence
--------------------------------
Every entry records :attr:`LicenseTerms.terms_url` -- where a human can check the claim --
and a :attr:`LicenseTerms.review_status`. ``needs_review`` means the classification below
was written from general knowledge of the licence rather than read off the linked terms
during authoring. Those entries still work, but the fetcher records them in the lock so
that M15.4's licence audit has a worklist instead of a vague instruction to "check the
licences". Marking everything ``confirmed`` would have been one word of work and would
have made the audit meaningless.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class Standing(StrEnum):
    """How a licence sits with a public, permissively-licensed project.

    Computed from the flags below, never authored -- the same rule AGENTS.md section 6
    applies to card confidence, for the same reason.
    """

    PERMISSIVE = "permissive"
    """Commercial use allowed, derivatives allowed, no copyleft. Fetch freely."""

    NEEDS_REVIEW = "needs-review"
    """Permissive by our flags, but nobody has checked those flags against the terms."""

    PER_RECORD = "per-record"
    """The collection-level statement is not authoritative: individual records carry their
    own terms. PGS Catalog is the case AGENTS.md section 4.8 warns about, and it is real --
    ``pgs_all_metadata_scores.csv`` carries a ``License/Terms of Use`` column with ten
    distinct values, most scores under the EBI default but a few dozen under CC BY-NC-ND
    and a handful restricted to academic research. Fetching the collection is fine;
    *using a given score* requires reading that score's own entry (M9.1)."""

    RESTRICTED = "restricted"
    """Non-commercial, no-derivatives, or share-alike. Requires explicit opt-in."""


@dataclass(frozen=True)
class LicenseTerms:
    """One licence, and what it allows us to do.

    The three booleans are about *our* uses, which are narrower than the licence as a
    whole. We never redistribute a payload (AGENTS.md 1.4 -- references are fetched, and
    ``data/references/`` is gitignored), so ``redistribution_ok`` is recorded for the
    M15.4 audit rather than consulted by the gate. ``derivative_ok`` is the one that bites
    in practice: a knowledge-pack entry or a computed score derived from a no-derivatives
    source is a problem even though the payload never leaves the machine.
    """

    id: str
    """SPDX identifier where one exists, otherwise a ``LicenseRef-`` id per the SPDX
    convention for licences outside the standard list."""

    name: str
    terms_url: str
    """Where the terms are actually published. Recorded so M15.4 can audit rather than
    take this table's word for it."""

    commercial_ok: bool
    derivative_ok: bool
    redistribution_ok: bool
    share_alike: bool
    attribution_required: bool

    authoritative: bool = True
    """False when the collection-level licence does not bind individual records."""

    review_status: str = "needs-review"
    """``confirmed`` only when the flags above were read off ``terms_url`` while writing
    this entry. Defaults to the honest answer, so forgetting to check cannot look like
    having checked."""

    notes: str = ""

    @property
    def standing(self) -> Standing:
        if not self.authoritative:
            return Standing.PER_RECORD
        if not (self.commercial_ok and self.derivative_ok) or self.share_alike:
            return Standing.RESTRICTED
        if self.review_status != "confirmed":
            return Standing.NEEDS_REVIEW
        return Standing.PERMISSIVE

    @property
    def needs_opt_in(self) -> bool:
        """True when fetching this source requires the operator to say so explicitly.

        Only :attr:`Standing.RESTRICTED` gates the fetch. ``PER_RECORD`` and
        ``NEEDS_REVIEW`` are loud, not blocking: refusing to download the PGS Catalog
        because 31 of its 6,970 scores are CC BY-NC-ND would block the other 6,939 for no
        reason, and the decision that actually matters there happens per score in M9.1.
        """
        return self.standing is Standing.RESTRICTED


_ENTRIES: tuple[LicenseTerms, ...] = (
    LicenseTerms(
        id="CC0-1.0",
        name="Creative Commons Zero v1.0 Universal",
        terms_url="https://creativecommons.org/publicdomain/zero/1.0/",
        commercial_ok=True,
        derivative_ok=True,
        redistribution_ok=True,
        share_alike=False,
        attribution_required=False,
        review_status="confirmed",
        notes="Public domain dedication; no conditions.",
    ),
    LicenseTerms(
        id="CC-BY-4.0",
        name="Creative Commons Attribution 4.0 International",
        terms_url="https://creativecommons.org/licenses/by/4.0/",
        commercial_ok=True,
        derivative_ok=True,
        redistribution_ok=True,
        share_alike=False,
        attribution_required=True,
        review_status="confirmed",
        notes="Attribution only. Cards sourced from CC-BY data must name the source.",
    ),
    LicenseTerms(
        id="CC-BY-SA-4.0",
        name="Creative Commons Attribution-ShareAlike 4.0 International",
        terms_url="https://creativecommons.org/licenses/by-sa/4.0/",
        commercial_ok=True,
        derivative_ok=True,
        redistribution_ok=True,
        share_alike=True,
        attribution_required=True,
        review_status="confirmed",
        notes=(
            "Share-alike is why this is restricted here despite allowing commercial use: "
            "a knowledge-pack entry derived from it would carry the copyleft into a "
            "repository that is otherwise permissively licensed."
        ),
    ),
    LicenseTerms(
        id="CC-BY-NC-SA-3.0-US",
        name="Creative Commons Attribution-NonCommercial-ShareAlike 3.0 United States",
        terms_url="https://creativecommons.org/licenses/by-nc-sa/3.0/us/",
        commercial_ok=False,
        derivative_ok=True,
        redistribution_ok=True,
        share_alike=True,
        attribution_required=True,
        review_status="confirmed",
        notes=(
            "SNPedia. AGENTS.md 4.8 trap 2: the most convenient trait-annotation corpus "
            "and the one that most constrains this project. Opt-in only, and prefer "
            "writing cards from primary literature."
        ),
    ),
    LicenseTerms(
        id="CC-BY-NC-ND-4.0",
        name="Creative Commons Attribution-NonCommercial-NoDerivatives 4.0 International",
        terms_url="https://creativecommons.org/licenses/by-nc-nd/4.0/",
        commercial_ok=False,
        derivative_ok=False,
        redistribution_ok=True,
        share_alike=False,
        attribution_required=True,
        review_status="confirmed",
        notes=(
            "Carried by a few dozen PGS Catalog scores. NoDerivatives is the sharper edge "
            "of the two restrictions for us: computing a score for an individual from the "
            "weights is plausibly a derivative work, so these are opt-in even for a run "
            "that never leaves the machine."
        ),
    ),
    LicenseTerms(
        id="GPL-3.0-or-later",
        name="GNU General Public License v3.0 or later",
        terms_url="https://www.gnu.org/licenses/gpl-3.0.en.html",
        commercial_ok=True,
        derivative_ok=True,
        redistribution_ok=True,
        share_alike=True,
        attribution_required=True,
        review_status="confirmed",
        notes=(
            "PLINK 2 and Beagle. Copyleft, so this table classifies it restricted -- and "
            "the tools installer deliberately does not apply the opt-in gate to it. The "
            "gate asks a data question ('would folding this into our corpus impose its "
            "licence on our output?'), and for a program we neither link against nor "
            "redistribute, but merely execute as a subprocess, the answer is no: running "
            "a GPL binary imposes nothing on the data it emits. See "
            "genetics/refs/tools.py, which states that reasoning where the decision is "
            "actually made."
        ),
    ),
    LicenseTerms(
        id="LicenseRef-US-Government-Public-Domain",
        name="US Government work, public domain (NCBI)",
        terms_url="https://www.ncbi.nlm.nih.gov/home/about/policies/",
        commercial_ok=True,
        derivative_ok=True,
        redistribution_ok=True,
        share_alike=False,
        attribution_required=False,
        notes=(
            "ClinVar and dbSNP. NCBI states its databases carry no restriction on use or "
            "redistribution; individual submitted records can carry third-party rights, "
            "which is why the ClinVar cards cite the submitter rather than the archive."
        ),
    ),
    LicenseTerms(
        id="LicenseRef-gnomAD-Open-Access",
        name="gnomAD open access (Broad Institute)",
        terms_url="https://gnomad.broadinstitute.org/policies",
        commercial_ok=True,
        derivative_ok=True,
        redistribution_ok=True,
        share_alike=False,
        attribution_required=False,
        notes=(
            "gnomAD publishes its aggregate frequency data for free use including "
            "commercial, with no restriction on redistribution. Load-bearing for the "
            "AGENTS.md 4.1 frequency gate, so a licence problem here would be a design "
            "problem, not a fetch problem."
        ),
    ),
    LicenseTerms(
        id="LicenseRef-Fort-Lauderdale",
        name="Fort Lauderdale / Toronto community resource terms",
        terms_url="https://www.internationalgenome.org/IGSR_disclaimer",
        commercial_ok=True,
        derivative_ok=True,
        redistribution_ok=True,
        share_alike=False,
        attribution_required=True,
        notes=(
            "1000 Genomes, HGDP, SGDP. Data are unrestricted; the convention is a "
            "publication-timing courtesy to the data producers rather than a licence "
            "condition, and it does not constrain analysis of one's own genome."
        ),
    ),
    LicenseTerms(
        id="LicenseRef-EBI-Terms-Of-Use",
        name="EMBL-EBI terms of use",
        terms_url="https://www.ebi.ac.uk/about/terms-of-use",
        commercial_ok=True,
        derivative_ok=True,
        redistribution_ok=True,
        share_alike=False,
        attribution_required=True,
        notes="GWAS Catalog. Post-2021 summary statistics are CC0; the catalogue itself is open.",
    ),
    LicenseTerms(
        id="LicenseRef-PGS-Catalog-Per-Score",
        name="PGS Catalog -- licence declared per score",
        terms_url="https://www.pgscatalog.org/about/#license",
        commercial_ok=True,
        derivative_ok=True,
        redistribution_ok=True,
        share_alike=False,
        attribution_required=True,
        authoritative=False,
        review_status="confirmed",
        notes=(
            "AGENTS.md 4.8 trap 1, verified rather than assumed: "
            "pgs_all_metadata_scores.csv carries a 'License/Terms of Use' column with ten "
            "distinct values -- the EBI default for most, but CC BY-NC-ND 4.0 for a few "
            "dozen and academic-research-only for a handful. Note the authoritative field "
            "is that metadata column; a scoring file's own header does not always repeat "
            "it (PGS000001's does not). M9.1 must read the column per score."
        ),
    ),
    LicenseTerms(
        id="LicenseRef-PharmGKB-CC-BY-SA-4.0",
        name="PharmGKB / ClinPGx data usage policy (CC BY-SA 4.0)",
        terms_url="https://www.pharmgkb.org/page/dataUsagePolicy",
        commercial_ok=True,
        derivative_ok=True,
        redistribution_ok=True,
        share_alike=True,
        attribution_required=True,
        notes=(
            "Share-alike, so restricted by this table's rule and opt-in by default. "
            "PharmGKB is the corpus behind the highest-value section in the app "
            "(AGENTS.md 3.1), so the opt-in is expected to be taken -- the point of "
            "gating it is that the share-alike obligation is recorded in the lock and "
            "reaches M15.4, not that the data is avoided."
        ),
    ),
    LicenseTerms(
        id="LicenseRef-CPIC-Open",
        name="CPIC open data",
        terms_url="https://cpicpgx.org/license/",
        commercial_ok=True,
        derivative_ok=True,
        redistribution_ok=True,
        share_alike=False,
        attribution_required=True,
        notes="CPIC guidelines and allele tables are freely available for any use with citation.",
    ),
    LicenseTerms(
        id="LicenseRef-PhyloTree-Academic-Attribution",
        name="PhyloTree mtDNA build 17 (van Oven), citation required",
        terms_url="https://www.phylotree.org/",
        commercial_ok=True,
        derivative_ok=True,
        redistribution_ok=True,
        share_alike=False,
        attribution_required=True,
        notes="Build 17, frozen 2016-02-18. Cite van Oven & Kayser 2009 on every mtDNA card.",
    ),
    LicenseTerms(
        id="LicenseRef-OMIM-No-Derivatives",
        name="OMIM terms (Johns Hopkins University)",
        terms_url="https://www.omim.org/help/agreement",
        commercial_ok=False,
        derivative_ok=False,
        redistribution_ok=False,
        share_alike=False,
        attribution_required=True,
        notes=(
            "AGENTS.md 4.8 trap 3. Forbids building a derivative database and forbids "
            "redistribution without a Johns Hopkins licence; requires a registered API key "
            "and weekly refresh. Hence user-supplied key only, never vendored, never "
            "cached long-term -- see the manifest entry's retention policy."
        ),
    ),
    LicenseTerms(
        id="LicenseRef-FinnGen-Free-Use",
        name="FinnGen public summary statistics terms",
        terms_url="https://www.finngen.fi/en/access_results",
        commercial_ok=True,
        derivative_ok=True,
        redistribution_ok=True,
        share_alike=False,
        attribution_required=True,
        notes=(
            "Summary statistics only; no individual-level data is public. FinnGen asks "
            "that the release be cited and that no attempt be made to re-identify "
            "participants."
        ),
    ),
)

LICENSES: Final[dict[str, LicenseTerms]] = {entry.id: entry for entry in _ENTRIES}


class UnknownLicenseError(KeyError):
    """Raised for a licence id absent from :data:`LICENSES`.

    Deliberately fatal at manifest-load time. The alternative -- treating an unrecognised
    licence as permissive, or as merely worth a warning -- would mean the one source
    nobody had thought about was the one source the gate did not apply to.
    """


def get(license_id: str) -> LicenseTerms:
    """Look up a licence, or raise :class:`UnknownLicenseError`."""
    try:
        return LICENSES[license_id]
    except KeyError:
        known = ", ".join(sorted(LICENSES))
        raise UnknownLicenseError(
            f"unknown licence id {license_id!r}. Add it to genetics.refs.licenses after "
            f"reading the terms -- an unclassified licence is not assumed permissive. "
            f"Known ids: {known}."
        ) from None


def standing(license_id: str) -> Standing:
    """Convenience wrapper over :attr:`LicenseTerms.standing`."""
    return get(license_id).standing
