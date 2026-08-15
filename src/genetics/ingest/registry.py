"""Vendor sniffing and the adapter registry (roadmap M1.3).

The plug-and-play requirement in AGENTS.md section 2 is a statement about *coupling*:
adding a vendor must not require touching an analysis module. This registry is the seam
that makes that checkable. An adapter supplies two things -- a sniffer over the first few
lines, and a parser producing the normalized table -- and nothing else in the codebase
learns its name.

Sniffing reads a bounded prefix of the file, never the whole thing. That is partly for
speed on a 677k-row export and partly because a sniffer with the full file in hand tends
to grow into a second parser.

Detection is deliberately *exclusive*: if two adapters claim a file, that is a conflict
worth failing on rather than resolving by registration order. Two vendors whose formats
overlap enough to be confusable is precisely the situation where picking one silently
produces a wrong parse.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from genetics.ingest.errors import IngestError, UnknownVendorError
from genetics.ingest.schema import GenotypeTable

SNIFF_LINES = 40
"""Enough to clear the ~17-line AncestryDNA comment block plus its column row, with
headroom for a vendor that comments more heavily."""

SNIFF_BYTES = 64 * 1024
"""Hard cap, so a pathological single-line file cannot be read into memory entire."""


@dataclass(frozen=True)
class SourceInfo:
    """Provenance for a parsed file. Goes into the run bundle (M4.1).

    Records the file *name*, never its contents. A filename is not genotype data, and
    knowing which export a run came from is the whole point of provenance.
    """

    vendor: str
    display_name: str
    path: str
    build: str
    array_version: str | None
    header_lines: int
    data_rows: int


@dataclass(frozen=True)
class ParseResult:
    """What an adapter returns: the normalized table plus what it learned on the way."""

    table: GenotypeTable
    source: SourceInfo


@dataclass(frozen=True)
class Adapter:
    """One vendor's ingest path."""

    vendor_id: str
    display_name: str
    sniff: Callable[[Sequence[str]], bool]
    """Given the first :data:`SNIFF_LINES` lines, does this look like our format?"""

    parse: Callable[[Path], ParseResult]

    verified_against_real_export: bool = False
    """False means the adapter has only ever seen a synthetic fixture. Surfaced by
    ``genetics ingest`` so nobody mistakes "it parsed" for "it was validated": the
    23andMe adapter is a seam-proving stub, and saying so is cheaper than discovering it
    at the point someone trusts a card built on it."""


_REGISTRY: dict[str, Adapter] = {}


def register(adapter: Adapter) -> Adapter:
    """Add an adapter. Returns it, so it can be used as a module-level assignment."""
    if adapter.vendor_id in _REGISTRY:
        raise ValueError(f"adapter {adapter.vendor_id!r} is already registered")
    _REGISTRY[adapter.vendor_id] = adapter
    return adapter


def adapters() -> tuple[Adapter, ...]:
    """Every registered adapter, in registration order."""
    _load_builtin_adapters()
    return tuple(_REGISTRY.values())


def get(vendor_id: str) -> Adapter:
    """Look an adapter up by id."""
    _load_builtin_adapters()
    try:
        return _REGISTRY[vendor_id]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY)) or "none"
        raise UnknownVendorError(
            f"no adapter registered as {vendor_id!r}. Registered adapters: {known}."
        ) from None


def read_prefix(path: Path) -> list[str]:
    """First :data:`SNIFF_LINES` lines, capped at :data:`SNIFF_BYTES`.

    Decoded leniently: a sniffer's job is to recognise a shape, and refusing to look at a
    file because of one bad byte would turn a fixable encoding problem into an
    unexplained "unknown vendor".
    """
    lines: list[str] = []
    consumed = 0
    with path.open("rb") as handle:
        for raw in handle:
            consumed += len(raw)
            lines.append(raw.decode("utf-8", errors="replace").rstrip("\r\n"))
            if len(lines) >= SNIFF_LINES or consumed >= SNIFF_BYTES:
                break
    return lines


def detect(path: Path) -> Adapter:
    """Identify the vendor, or raise :class:`UnknownVendorError`."""
    _load_builtin_adapters()

    if not path.is_file():
        raise UnknownVendorError(f"no such file: {path}")

    prefix = read_prefix(path)
    if not prefix:
        raise UnknownVendorError(f"{path.name} is empty")

    claimed = [adapter for adapter in _REGISTRY.values() if adapter.sniff(prefix)]

    if len(claimed) == 1:
        return claimed[0]

    if not claimed:
        known = ", ".join(a.display_name for a in _REGISTRY.values()) or "none registered"
        raise UnknownVendorError(
            f"{path.name} does not match any known vendor layout. Recognised: {known}. "
            "If this is a new vendor, add an adapter in genetics.ingest and register it -- "
            "no analysis module should need changing."
        )

    names = ", ".join(a.vendor_id for a in claimed)
    raise IngestError(
        f"{path.name} was claimed by more than one adapter ({names}). Their sniffers "
        "overlap; tighten one rather than letting registration order decide, because the "
        "wrong choice here mis-parses silently."
    )


_builtins_loaded = False


def _load_builtin_adapters() -> None:
    """Import the shipped adapters on first use.

    Lazy, and via import side effect, so that adding a vendor means adding a module and
    one line here -- not editing anything that analyses data. The flag keeps repeated
    calls cheap and stops the duplicate-registration guard from firing on re-import.
    """
    global _builtins_loaded
    if _builtins_loaded:
        return
    _builtins_loaded = True

    from genetics.ingest import ancestry, vendor_23andme  # noqa: F401
