"""Private score records held compressed, one parsed at a time.

A genome-wide score's record carries a term for every scoring row: about 1.9 GB once parsed,
743 MB as compact JSON and 46 MB gzip-compressed (PGS002143, 966,283 rows; measured
2026-11-01). A run that kept the pack's records parsed until saving exhausted a 32 GB
machine. :class:`ScoreRecords` keeps each compressed and parses a fresh copy on every access,
so a caller that iterates holds one at a time.

The compressed bytes are exactly what a bundle saves as ``pgs-<card id>.run.json.gz`` (from
format 25): canonical JSON, gzip with a zero timestamp, so the same record compresses to the
same bytes on this machine. From format 26 the JSON is ASCII-escaped, making it the exact
text a card's ``score_sha256`` digests: a reader checks that digest on the stored bytes
instead of re-serialising the parsed record, which took 6 s for a 966,283-row record.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import zlib
from collections.abc import Iterator, Mapping
from typing import Any, Final

from genetics.pgs.catalog import PgsError

_FILE: Final[re.Pattern[str]] = re.compile(r"pgs-([a-z0-9][a-z0-9_]*)\.run\.json\.gz")


def score_file_name(card_id: str) -> str:
    """The bundle file holding one polygenic card's record, on the ``*.run.json.gz`` rule."""
    name = f"pgs-{card_id}.run.json.gz"
    if _FILE.fullmatch(name) is None:
        raise PgsError("A polygenic card id cannot name a score record file.")
    return name


def is_score_file_name(name: str) -> bool:
    return isinstance(name, str) and _FILE.fullmatch(name) is not None


def encode(record: Mapping[str, Any]) -> bytes:
    """Canonical JSON for one record; NaN and infinity are refused, as everywhere else.

    The text :func:`genetics.pgs.cards.record_digest` hashes, byte for byte. Format 25 wrote
    it unescaped (``ensure_ascii=False``); such a record's digest is recomputed when read.
    """
    return json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
        "ascii"
    )


class ScoreRecords(Mapping[str, Mapping[str, Any]]):
    """Private score records by polygenic card id, compressed until accessed."""

    def __init__(self, compressed: Mapping[str, bytes] | None = None) -> None:
        self._compressed = dict(compressed or {})

    @classmethod
    def of(cls, records: Mapping[str, Mapping[str, Any]] | None) -> ScoreRecords:
        """``records`` as is when already compressed, otherwise compressed one by one."""
        if isinstance(records, ScoreRecords):
            return records
        held = cls()
        for key, record in (records or {}).items():
            held.add(key, record)
        return held

    def add(self, key: str, record: Mapping[str, Any]) -> dict[str, Any]:
        """Store ``record`` compressed and return its JSON form, as a reader parses it."""
        if key in self._compressed:
            raise PgsError(f"A score record for {key!r} is already held.")
        text = encode(record)
        self._compressed[key] = gzip.compress(text, compresslevel=6, mtime=0)
        parsed: dict[str, Any] = json.loads(text)
        return parsed

    def restore(self, key: str, data: bytes) -> dict[str, Any]:
        """Hold a record saved compressed by an interrupted run, and return its JSON form.

        Held only once it decodes, so a damaged saved record leaves nothing behind it.
        """
        if key in self._compressed:
            raise PgsError(f"A score record for {key!r} is already held.")
        self._compressed[key] = data
        try:
            return self.parsed(key)[0]
        except PgsError:
            del self._compressed[key]
            raise

    def compressed(self, key: str) -> bytes:
        return self._compressed[key]

    def __getitem__(self, key: str) -> Mapping[str, Any]:
        return self.parsed(key)[0]

    def parsed(self, key: str) -> tuple[dict[str, Any], str]:
        """A fresh parse of one record, and the sha256 of the JSON text it was parsed from.

        When that digest equals the card's ``score_sha256``, the text is the record's
        canonical form and the record need not be serialised again to check it.
        """
        data = self._compressed[key]
        try:
            text = gzip.decompress(data)
            record = json.loads(text)
        except (OSError, EOFError, zlib.error, ValueError) as exc:
            raise PgsError(f"The saved score record for {key!r} cannot be decoded.") from exc
        if not isinstance(record, dict):
            raise PgsError(f"The saved score record for {key!r} is not an object.")
        return record, hashlib.sha256(text).hexdigest()

    def __iter__(self) -> Iterator[str]:
        return iter(self._compressed)

    def __len__(self) -> int:
        return len(self._compressed)

    def __repr__(self) -> str:
        # Never the records: they are private, and even an aggregate dose identifies.
        return f"ScoreRecords({sorted(self._compressed)!r})"
