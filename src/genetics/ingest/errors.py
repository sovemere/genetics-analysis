"""Ingest failures (roadmap M1.4).

Two rules shape every message in this module, and they pull against each other.

**Fail loudly** (AGENTS.md 6). A silently mis-parsed genotype becomes a confident, wrong,
personal health claim. So ingest rejects rather than guesses, and the message has to say
enough that the reader can fix the file or the adapter.

**Never echo a genotype** (AGENTS.md 1.3). An exception message is one of the easiest
ways for genotype content to escape: it goes to a terminal, a log, a CI transcript, and
eventually a pasted issue. So a message may name the *row number*, the *rsID* and the
*shape* of the problem -- never the allele values, never the offending line.

A bare rsID is not a genotype and is explicitly permitted: the privacy scanner's negative
cases assert as much, and without it "which row?" has no useful answer.

:class:`IngestError` enforces the second rule in its constructor, so an error type added
later cannot quietly reintroduce the leak.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from genetics.privacy import assert_no_genotype, redact

_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_ ]{0,29}$", re.IGNORECASE)
"""What a column *name* looks like. A data field does not: a genotype row always carries
a bare numeric position, which has no leading letter."""


def describe_columns(columns: Sequence[str]) -> str:
    """Render observed column names for an error message, without ever echoing data.

    Naming the columns is what makes a "renamed or reordered file" message actionable, so
    this is worth getting right rather than dropping.

    The trap: when the column header row is *missing* -- a truncated export, the exact
    case this check exists to catch -- the first uncommented line is a genotype row, and
    the obvious ``f"got {columns}"`` puts a genotype in an exception message. The privacy
    scanner does not save us there, because a Python list renders comma-separated and its
    row patterns expect whitespace or escaped tabs between fields.

    So: show the names only when every field looks like an identifier, and say what was
    actually found otherwise. The fallback message is the more useful one anyway -- "this
    looks like a data row" names the real problem, which is that the header is gone.
    """
    if columns and all(_IDENTIFIER.match(c) for c in columns):
        return f"got {list(columns)}"
    return (
        f"got {len(columns)} field(s) that do not look like column names -- this line "
        "appears to be a data row, so the column header row is missing or the file is "
        "truncated"
    )


def safe_detail(text: str) -> str:
    """Last-resort redaction for a message assembled from file content.

    Prefer not putting file content in a message at all. Where that is unavoidable, this
    at least keeps the known row shapes out. It is a net, not a guarantee.
    """
    return redact(text)


class IngestError(Exception):
    """Base for every refusal to parse.

    Constructing one runs the message through the leak scanner. This is not paranoia
    about the messages written today -- it is that error messages are exactly where a
    future "just include the line so we can debug it" lands, and that change should fail
    the test suite rather than ship.
    """

    def __init__(self, message: str) -> None:
        assert_no_genotype(message, context="an ingest error message")
        super().__init__(message)


class UnknownVendorError(IngestError):
    """No registered adapter recognised the file."""


class MalformedHeaderError(IngestError):
    """The comment block or the column header row is not the expected shape."""


class UnsupportedBuildError(IngestError):
    """The file declares a reference build this pipeline does not accept.

    Everything downstream -- ClinVar positions, PGS scoring files, the imputation panel --
    is GRCh37. A build-38 file parsed as 37 would put every variant at the wrong locus and
    return cards about the wrong genes, with no symptom other than being wrong.
    """


class ColumnCountError(IngestError):
    """A data row has the wrong number of fields."""


class MalformedRowError(IngestError):
    """A data row is structurally invalid: bad allele token, bad position, bad chromosome."""


class EmptyExportError(IngestError):
    """The file parsed cleanly and contained no markers."""
