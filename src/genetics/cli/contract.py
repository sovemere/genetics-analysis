"""The agent CLI's JSON contract: one versioned schema, one tag, one error shape (M13.2).

``agent_schema.json`` beside this module is the contract. It describes every document the
agent read commands print (``runs list``, ``runs show``, ``runs show --section``, ``runs
card``, ``runs qc``, ``runs search``, ``cards evidence``, ``cards search``) and the error
document every ``--json`` command prints when it fails. ``genetics schema`` prints it, and
``docs/agent_schema.md`` states the rules around it.

**Every described document names itself.** :func:`tagged` puts
``"schema": {"name": ..., "version": ...}`` first, so a reader can tell a card from an error
without knowing which command produced it, and can tell which version of the document to
check it against.

**One version for the whole contract.** The bundle has ``format_version`` for the saved
record; this number is for what the CLI prints around it. It moves when any described shape
changes, and only by addition: a key is never removed or given another meaning, as in the
bundle (see ``BUNDLE_FORMAT_VERSION``). ``tests/test_agent_schema.py`` pins a digest of each
version's shape, so the document cannot change under a number that has already shipped.

**One error shape.** :func:`refuse` is the only place a ``--json`` failure is written. Before
M13.2 ``runs``, ``cards evidence`` and ``hla calls`` printed ``error`` as ``{kind, message}``
while ``pgx`` and ``pgs`` printed it as a bare string.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Sequence
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, NoReturn

import typer

if TYPE_CHECKING:
    from genetics.engine.search import Query

AGENT_SCHEMA_VERSION: Final[int] = 4
"""The version every tagged document carries. Bump it with any change to a described shape."""

SCHEMA_PATH: Final[Path] = Path(__file__).with_name("agent_schema.json")


@cache
def _document() -> dict[str, Any]:
    loaded = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict) or loaded.get("version") != AGENT_SCHEMA_VERSION:
        raise RuntimeError(
            f"{SCHEMA_PATH.name} does not describe agent schema version {AGENT_SCHEMA_VERSION}"
        )
    return loaded


def document() -> dict[str, Any]:
    """The whole schema document. A copy, so a caller cannot edit the cached one."""
    return copy.deepcopy(_document())


def payloads() -> list[dict[str, Any]]:
    """Each described payload: its name, the command that prints it, and its privacy facts."""
    return copy.deepcopy(_document()["x-payloads"])


def payload_names() -> tuple[str, ...]:
    return tuple(entry["name"] for entry in _document()["x-payloads"])


def payload_schema(name: str) -> dict[str, Any]:
    """A self-contained JSON Schema for one payload, for a validator to be handed directly.

    Raises ``KeyError`` for a name the document does not describe.
    """
    source = _document()
    if name not in payload_names():
        raise KeyError(name)
    return {
        "$schema": source["$schema"],
        "$id": f"{source['$id']}:{name}",
        "title": f"genetics agent CLI payload: {name}",
        "version": source["version"],
        "$ref": f"#/$defs/{name}",
        "$defs": copy.deepcopy(source["$defs"]),
    }


def tagged(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """``payload`` with its schema tag first. The name must be one the document describes."""
    if name not in payload_names():
        raise ValueError(f"{name!r} is not a payload the agent schema describes")
    if "schema" in payload:
        raise ValueError(f"{name} payload already has a 'schema' key")
    return {"schema": {"name": name, "version": AGENT_SCHEMA_VERSION}} | payload


def error_payload(kind: str, message: str) -> dict[str, Any]:
    """The one error document. ``kind`` is for a program; ``message`` is for a person."""
    return tagged("error", {"ok": False, "error": {"kind": kind, "message": message}})


def run_error_kind(exc: Exception) -> str:
    """The kind for a saved run that could not be opened, the same from every command.

    ``version`` is the one that has to survive: M4.2 requires "written by a newer engine" to
    be distinguishable from "this file is damaged", and an agent reading ``--json`` cannot
    draw that distinction out of prose. ``io`` exists because the store raises ``OSError``,
    not ``BundleError``, when the disk refuses -- a locked file on Windows, a permission
    change, a removable drive that is no longer there.

    Shared by ``runs``, ``pgx calls`` and ``hla calls`` since the M13.2 review: before it,
    ``hla calls`` reported a newer-format run as ``hla`` and ``pgx calls`` a disk failure
    as ``pgx``, so one run gave three kinds depending on which command opened it.
    """
    from genetics.run.bundle import BundleIntegrityError, BundleVersionError
    from genetics.run.store import RunNotFoundError

    if isinstance(exc, BundleVersionError):
        return "version"
    if isinstance(exc, RunNotFoundError):
        return "not-found"
    if isinstance(exc, BundleIntegrityError):
        return "integrity"
    if isinstance(exc, OSError):
        return "io"
    return "bundle"


def refuse(kind: str, message: str, *, as_json: bool, code: int = 1) -> NoReturn:
    """Report a failure and exit non-zero: the error document on stdout, or a line on stderr.

    ``code`` is 2 where the command line itself was wrong and 1 where it was well formed but
    could not be carried out; see docs/agent_schema.md for which commands hold to that.
    """
    if as_json:
        typer.echo(json.dumps(error_payload(kind, message), indent=2))
    else:
        typer.secho(message, fg=typer.colors.RED, err=True)
    raise typer.Exit(code=code)


def search_query(words: Sequence[str], *, as_json: bool) -> Query:
    """A search command's query, or a usage error (exit 2) before anything is read (M13.3).

    Shared by ``cards search`` and ``runs search`` so both refuse the same queries under the
    same kinds. The kinds are written out here, not carried on the exceptions, so the test
    that reads every kind from this package's source finds them.
    """
    from genetics.engine import search

    try:
        return search.parse_query(" ".join(words))
    except search.GenotypeQueryError as exc:
        refuse("genotype-in-query", str(exc), as_json=as_json, code=2)
    except search.EmptyQueryError as exc:
        refuse("empty-query", str(exc), as_json=as_json, code=2)
