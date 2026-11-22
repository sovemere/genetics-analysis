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
        id="LicenseRef-HIBAG-HLARES-Unspecified",
        name="HIBAG HLARES published parameters; separate model terms unspecified",
        terms_url="https://hibag.s3.amazonaws.com/hlares_index.html",
        commercial_ok=False,
        derivative_ok=False,
        redistribution_ok=False,
        share_alike=False,
        attribution_required=True,
        review_status="confirmed",
        notes="Published explicitly for HLA imputation, but no separate model licence is "
        "displayed. These flags mean permission is unestablished, not an asserted prohibition. "
        "Do not inherit the software GPL or article CC-BY. Explicit source opt-in required. "
        "Read 2026-11-22 (M15.4), page updated 2026-09-19: still no licence or terms for the "
        "model files; they 'can be used by researchers', were estimated from GlaxoSmithKline "
        "trials and HapMap 2, and a published analysis should cite the HIBAG papers. The "
        "classification is confirmed as unestablished permission, which keeps the opt-in.",
    ),
    LicenseTerms(
        id="LicenseRef-HapMap-Public-Domain",
        name="HapMap numerical data, public domain",
        terms_url="https://www.genome.gov/11511175/about-the-international-hapmap-project-fact-sheet",
        commercial_ok=True,
        derivative_ok=True,
        redistribution_ok=True,
        share_alike=False,
        attribution_required=True,
        review_status="confirmed",
        notes="NHGRI states that HapMap data were released into the public domain. "
        "The GRCh37 numerical maps are Auton/Browning's coordinate/PLINK transformations; "
        "retain source attribution and do not vendor the archive or its README prose.",
    ),
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
        id="MIT",
        name="MIT License",
        terms_url="https://spdx.org/licenses/MIT.html",
        commercial_ok=True,
        derivative_ok=True,
        redistribution_ok=True,
        share_alike=False,
        attribution_required=True,
        review_status="confirmed",
        notes=(
            "Permissive; the only condition is that the notice travels with the copy. "
            "Arrives with y_tree_isogg_grch37 (M5.7), where the grant is what makes the "
            "marker table usable in a public checkout at all -- see that manifest entry "
            "for why the alternative was not."
        ),
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
        review_status="confirmed",
        notes=(
            "ClinVar and dbSNP. Read 2026-11-22 (M15.4): 'NCBI itself places no restrictions "
            "on the use or distribution of the data', but submitters 'may claim patent, "
            "copyright, or other intellectual property rights', and NCBI grants none of its "
            "own. Acknowledgement is requested for NLM pages, not required for the data. "
            "(This note said until M15.4's review that the ClinVar cards cite the submitter "
            "rather than the archive; they cite ClinVar's VCV records.)"
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
        review_status="confirmed",
        notes=(
            "Read 2026-11-22 (M15.4) from the policy page's source, "
            "github.com/broadinstitute/gnomad-browser browser/about/policies/terms.md, "
            "since the page itself renders only with JavaScript: the primary exome and "
            "genome data are 'available free of restrictions under the Creative Commons "
            "Zero Public Domain Dedication'; attribution is requested, not required. One "
            "term CC0 does not carry, which is why this is not filed as CC0-1.0: 'All users "
            "of gnomAD data agree to not attempt to reidentify participants.' SpliceAI "
            "annotations are CC BY-NC 4.0; the r2.1.1 sites VCFs this pipeline reads carry "
            "none. Load-bearing for the AGENTS.md 4.1 frequency gate."
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
        review_status="confirmed",
        notes=(
            "1000 Genomes, HGDP, SGDP. Read 2026-11-22 (M15.4): 1000 Genomes data are "
            "'available without embargo, following the final publication'; use 'should be "
            "cited'; and the EMBL-EBI terms IGSR defers to place 'no additional restrictions "
            "on the use or redistribution of the data' beyond the original owners'. No data "
            "licence is named. HGDP's genotypes are withdrawn and SGDP's gated samples are "
            "not fetched; only 1000 Genomes is used under this entry."
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
        review_status="confirmed",
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
            "reaches M15.4, not that the data is avoided. Superseded at M10.1, when the "
            "October 2026 archives were found to carry BY-NC-SA notices; no source uses it, "
            "and it stays so that a lock or saved run written before then still reads."
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
        notes=(
            "CPIC guidelines and allele tables are freely available for any use with "
            "citation. Superseded at M10.1 by LicenseRef-CPIC-Database-ClinPGx; no source "
            "uses it, and it stays so that a lock or saved run written before then still reads."
        ),
    ),
    LicenseTerms(
        id="CC-BY-NC-SA-4.0",
        name="Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International",
        terms_url="https://creativecommons.org/licenses/by-nc-sa/4.0/",
        commercial_ok=False,
        derivative_ok=True,
        redistribution_ok=True,
        share_alike=True,
        attribution_required=True,
        review_status="confirmed",
        notes=(
            "ClinPGx October 2026 archive LICENSE.txt notices; July 2025 clinical "
            "annotations retain BY-SA. No payloads are vendored."
        ),
    ),
    LicenseTerms(
        id="LicenseRef-CPIC-Database-ClinPGx",
        name="CPIC database: CC0 curated content plus ClinPGx database/API terms",
        terms_url="https://github.com/cpicpgx/cpic-data/blob/v1.60.0/LICENSE.md",
        commercial_ok=False,
        derivative_ok=True,
        redistribution_ok=True,
        share_alike=True,
        attribution_required=True,
        review_status="confirmed",
        notes=(
            "Release license grants CC0 for curated content, but paragraph 6 also binds "
            "database/API users to ClinPGx data usage policy. Current ClinPGx archive notices "
            "and site footer say BY-NC-SA; older notices say BY-SA. This classification does "
            "not relicense all CPIC content as BY-NC-SA. Settled at M15.4 (2026-11-22) by "
            "taking the stricter reading, not by choosing between them: paragraph 6 links its "
            "'these licensing and terms of use' to the ClinPGx policy, which renders only "
            "with JavaScript and could not be read. Both readings are met: the use is "
            "personal and non-commercial, nothing derived from the database is committed "
            "(guideline cards hold selectors and paper citations, and the content is read "
            "from the local fetch at run time), and nothing is redistributed."
        ),
    ),
    LicenseTerms(
        id="LicenseRef-PhyloTree-Academic-Attribution",
        name="PhyloTree mtDNA build 17 (van Oven), citation required",
        terms_url="https://www.phylotree.org/",
        commercial_ok=True,
        derivative_ok=True,
        redistribution_ok=False,
        share_alike=False,
        attribution_required=True,
        review_status="confirmed",
        notes=(
            "Build 17, frozen 2016-02-18. Cite van Oven & Kayser 2009 on every mtDNA card. "
            "Read 2026-11-22 (M15.4): the site states no licence, no copyright notice and no "
            "academic or non-commercial restriction (the 'Academic' in this id predates that "
            "reading; renaming it would change every lock and saved run that names it). It "
            "asks for the citation and calls the tree 'a framework for evolutionary, "
            "anthropological, medical, forensic, and genealogical researchers'. With no "
            "grant, redistribution is not assumed; it is fetched, never vendored. What a "
            "card takes from it is factual: which positions define which branch. Contrast "
            "HIBAG, also unlicensed, where the model file itself is what is used."
        ),
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
            "cached long-term -- see the manifest entry's retention policy. Left "
            "needs-review at M15.4 (2026-11-22): never fetched, no stage reads it, and the "
            "classification is already the most restrictive the table has."
        ),
    ),
    LicenseTerms(
        id="LicenseRef-FinnGen-Free-Use",
        name="FinnGen public summary statistics terms",
        terms_url="https://www.finngen.fi/en/access_results",
        commercial_ok=True,
        derivative_ok=True,
        redistribution_ok=False,
        share_alike=False,
        attribution_required=True,
        review_status="confirmed",
        notes=(
            "Summary statistics only; no individual-level data is public. Read 2026-11-22 "
            "(M15.4): 'The FinnGen results are publicly available and may be freely used by "
            "the scientific community and other interested parties'; they 'are not intended "
            "to serve as a basis for product development, marketing activities, or "
            "health-related claims', and commercial use is 'the sole responsibility of the "
            "user'. Acknowledge the study and cite Kurki et al. 2023. No licence is named and "
            "no redistribution grant is given, so none is assumed. This note said until then "
            "that FinnGen asked users not to re-identify participants; the page says no such "
            "thing. The page now also offers a form that emails download instructions; "
            "AGENTS.md 5.2 records the files on public storage without one, as verified at "
            "M2.3 and not re-checked here. Not fetched; no stage reads it."
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


@dataclass(frozen=True)
class PgsTerms:
    """A score's metadata terms; unknown terms are never granted by opt-in."""

    status: str
    license_id: str | None
    reason: str

    def to_json(self) -> dict[str, object]:
        terms = get(self.license_id) if self.license_id is not None else None
        return {
            "status": self.status,
            "license_id": self.license_id,
            "reason": self.reason,
            "terms_url": terms.terms_url if terms else None,
            "commercial_ok": terms.commercial_ok if terms else None,
            "derivative_ok": terms.derivative_ok if terms else None,
            "share_alike": terms.share_alike if terms else None,
            "attribution_required": terms.attribution_required if terms else None,
        }

    def require_usable(self, *, opt_in: bool = False) -> None:
        if self.status == "permissive" or (self.status == "restricted" and opt_in):
            return
        raise ValueError(f"PGS score licence is {self.status}: {self.reason}")


def classify_pgs_terms(raw: str) -> PgsTerms:
    """Recognize complete, reviewed terms only, never an embedded licence substring.

    The registry already records the obligations of supported CC licences. Free-text
    academic/re-identification conditions remain unknown until reviewed explicitly.
    Source copyright suffixes are allowed only for the Catalog's documented CC form.
    """
    value = " ".join(raw.split())
    if not value:
        return PgsTerms("missing", None, "No score-specific terms supplied by metadata.")
    ebi = {
        "https://www.ebi.ac.uk/about/terms-of-use",
        "https://www.ebi.ac.uk/about/terms-of-use/",
        "EMBL-EBI Terms of Use",
        "EBI Terms of Use",
        "PGS obtained from the Catalog should be cited appropriately, and used in accordance "
        "with any licensing restrictions set by the authors. See EBI Terms of Use "
        "(https://www.ebi.ac.uk/about/terms-of-use/) for additional details.",
    }
    if value in ebi:
        return PgsTerms(
            "permissive",
            "LicenseRef-EBI-Terms-Of-Use",
            "Explicit EMBL-EBI default terms; cite the score and its authors.",
        )
    for license_id in ("CC0-1.0", "CC-BY-4.0", "CC-BY-SA-4.0", "CC-BY-NC-ND-4.0"):
        terms = get(license_id)
        aliases = {license_id, terms.terms_url, terms.terms_url.rstrip("/")}
        # PGS publishes the full CC title followed by the SPDX abbreviation and notice.
        title = terms.name
        if license_id == "CC-BY-NC-ND-4.0":
            title = "Creative Commons Attribution-NonCommercial-NoDerivatives 4.0 International"
        if license_id == "CC-BY-SA-4.0":
            title = "Creative Commons Attribution-ShareAlike 4.0 International"
        abbreviation = license_id.replace("-", " ", 1).replace("-4.0", " 4.0")
        full = value in {f"{title} ({abbreviation})", f"{title} ({abbreviation})."}
        if license_id == "CC-BY-NC-ND-4.0":
            full = full or value in {
                f"{title} ({abbreviation}). {symbol} 2020 Ambry Genetics."
                for symbol in ("©", "\ufffd")
            }
        if license_id == "CC-BY-NC-ND-4.0" and value == (
            f"{title} ({abbreviation}). Parties interested in using the scores for commercial "
            "purposes should contact 23andMe at publication-review@23andme.com."
        ):
            full = True
        if license_id == "CC0-1.0":
            aliases.add("CC0 1.0 Universal (CC0 1.0) Public Domain Dedication")
        if value in aliases or full:
            status = "restricted" if terms.needs_opt_in else "permissive"
            return PgsTerms(status, license_id, "Score-specific Creative Commons terms recorded.")
    return PgsTerms("unknown", None, "Unrecognized score-specific terms require explicit review.")
