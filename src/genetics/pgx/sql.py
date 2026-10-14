"""Read PostgreSQL dump data without a SQL engine or executing any statement.

COPY text and pg_dump --inserts are independent encodings of the same tables.
Keep source scalars as strings/null so no precision or authored wording is lost.
"""

from __future__ import annotations

import gzip
import re
from collections.abc import Iterator
from pathlib import Path

from genetics.refs.postprocess import ProcessError

Row = dict[str, str | None]
Tables = dict[str, list[Row]]

# Full tables, not a selected allele list. These required columns are the v1.60.0
# join contract; additional source columns survive verbatim.
REQUIRED = {
    "gene": ("symbol", "chr", "chromosequenceid", "lookupmethod", "version"),
    "allele_definition": (
        "id",
        "version",
        "genesymbol",
        "name",
        "pharmvarid",
        "matchesreferencesequence",
        "structuralvariation",
    ),
    "sequence_location": (
        "id",
        "version",
        "genesymbol",
        "chromosomelocation",
        "dbsnpid",
        "position",
    ),
    "allele_location_value": ("alleledefinitionid", "locationid", "variantallele", "version"),
    "allele": (
        "id",
        "version",
        "genesymbol",
        "name",
        "definitionid",
        "functionalstatus",
        "clinicalfunctionalstatus",
        "clinicalfunctionalsubstrate",
        "activityvalue",
        "citations",
        "strength",
        "functioncomments",
    ),
    "gene_result": ("id", "genesymbol", "result", "activityscore", "version"),
    "gene_result_diplotype": ("id", "functionphenotypeid", "diplotype", "diplotypekey"),
    "gene_result_lookup": (
        "id",
        "phenotypeid",
        "lookupkey",
        "function1",
        "function2",
        "activityvalue1",
        "activityvalue2",
        "totalactivityscore",
        "description",
    ),
    "publication": ("id", "pmid", "doi", "title", "version"),
    "guideline": ("id", "name", "url", "genes", "version"),
    "pair": ("pairid", "genesymbol", "drugid", "guidelineid", "cpiclevel", "citations"),
    "recommendation": (
        "id",
        "guidelineid",
        "drugid",
        "classification",
        "lookupkey",
        "phenotypes",
        "drugrecommendation",
        "version",
    ),
    "drug": ("drugid", "name", "version"),
    "file_note": ("type", "entityid", "note", "ordinal", "version"),
    "file_artifact": ("id", "entityids", "type", "filename", "url"),
    "term": ("id", "category", "term", "version"),
}

_COPY = re.compile(r"^COPY cpic\.(\w+) \(([^\n]+)\) FROM stdin;$")
_INSERT = re.compile(r"^INSERT INTO cpic\.(\w+) \(([^\n]+)\) VALUES \((.*)\);$", re.S)
_ESCAPES = {"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v", "\\": "\\"}


def copy_value(value: str) -> str | None:
    if value == r"\N":
        return None
    result: list[str] = []
    i = 0
    while i < len(value):
        if value[i] != "\\":
            result.append(value[i])
            i += 1
            continue
        i += 1
        if i == len(value):
            raise ProcessError("Truncated PostgreSQL COPY escape.")
        char = value[i]
        if char in _ESCAPES:
            result.append(_ESCAPES[char])
            i += 1
        elif char in "01234567":
            match = re.match(r"[0-7]{1,3}", value[i:])
            assert match is not None
            result.append(chr(int(match[0], 8)))
            i += len(match[0])
        elif char == "x":
            match = re.match(r"[0-9a-fA-F]{1,2}", value[i + 1 :])
            if match is None:
                raise ProcessError("Malformed PostgreSQL hex escape.")
            result.append(chr(int(match[0], 16)))
            i += 1 + len(match[0])
        else:
            raise ProcessError("Unsupported PostgreSQL COPY escape.")
    return "".join(result)


def _insert_values(text: str) -> list[str | None]:
    values: list[str | None] = []
    i = 0
    while i < len(text):
        while i < len(text) and text[i].isspace():
            i += 1
        if i == len(text):
            raise ProcessError("Empty INSERT value.")
        if text[i] == "'":
            i += 1
            chars: list[str] = []
            while i < len(text):
                if text[i] == "'":
                    if i + 1 < len(text) and text[i + 1] == "'":
                        chars.append("'")
                        i += 2
                        continue
                    i += 1
                    break
                chars.append(text[i])
                i += 1
            else:
                raise ProcessError("Unterminated INSERT string.")
            values.append("".join(chars))
        else:
            end = text.find(",", i)
            end = len(text) if end == -1 else end
            token = text[i:end].strip()
            if token == "NULL":
                values.append(None)
            elif token in {"true", "false"}:
                values.append("t" if token == "true" else "f")
            elif re.fullmatch(r"-?\d+(?:\.\d+)?", token):
                values.append(token)
            else:
                raise ProcessError(
                    "INSERT contains an unsupported expression; SQL is never executed."
                )
            i = end
        while i < len(text) and text[i].isspace():
            i += 1
        if i < len(text):
            if text[i] != ",":
                raise ProcessError("Malformed INSERT delimiter.")
            i += 1
            if not text[i:].strip():
                raise ProcessError("Trailing INSERT delimiter.")
    return values


def _columns(table: str, text: str) -> list[str]:
    columns = [c.strip().strip('"') for c in text.split(",")]
    if (
        len(columns) != len(set(columns))
        or any(re.fullmatch(r"[a-z][a-z0-9_]*", c) is None for c in columns)
        or not set(REQUIRED[table]) <= set(columns)
    ):
        raise ProcessError(f"CPIC {table}: missing, duplicate or malformed columns.")
    return columns


def _statements(lines: Iterator[str], first: str) -> str:
    """Find a SQL terminator outside standard-conforming single quoted strings."""
    parts: list[str] = []
    quoted = False
    line = first
    while True:
        parts.append(line)
        i = 0
        while i < len(line):
            if line[i] == "'":
                if quoted and i + 1 < len(line) and line[i + 1] == "'":
                    i += 2
                    continue
                quoted = not quoted
            elif line[i] == ";" and not quoted:
                if line[i + 1 :].strip():
                    raise ProcessError("Multiple SQL statements in INSERT data.")
                return "".join(parts).rstrip("\r\n")
            i += 1
        try:
            line = next(lines)
        except StopIteration as exc:
            raise ProcessError("Truncated CPIC INSERT statement.") from exc


def read_dump(path: Path, *, mode: str) -> Tables:
    if mode not in {"copy", "inserts"}:
        raise ProcessError("Unknown CPIC dump encoding.")
    tables: Tables = {table: [] for table in REQUIRED}
    seen: set[str] = set()
    copied: set[str] = set()
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        lines = iter(handle)
        for line in lines:
            text = line.rstrip("\r\n")
            if (
                text.startswith("SET standard_conforming_strings")
                and text != "SET standard_conforming_strings = on;"
            ):
                raise ProcessError("CPIC dump must use standard-conforming strings.")
            if schema := re.fullmatch(r"CREATE TABLE cpic\.(\w+) \(", text):
                table = schema[1]
                columns = []
                for declaration in lines:
                    declaration = declaration.strip()
                    if declaration == ");":
                        break
                    column = declaration.split(" ", 1)[0].strip('"')
                    if re.fullmatch(r"[a-z][a-z0-9_]*", column):
                        columns.append(column)
                else:
                    raise ProcessError("Truncated CPIC table schema.")
                if table in REQUIRED:
                    _columns(table, ", ".join(columns))
                    seen.add(table)
            elif text.startswith("COPY cpic."):
                if mode != "copy":
                    raise ProcessError("COPY in inserts dump.")
                match = _COPY.fullmatch(text)
                if match is None:
                    raise ProcessError("Malformed CPIC COPY header.")
                table = match[1]
                if table in copied:
                    raise ProcessError(f"Repeated CPIC COPY block: {table}.")
                seen.add(table)
                copied.add(table)
                columns = _columns(table, match[2]) if table in REQUIRED else []
                for data in lines:
                    data = data.rstrip("\r\n")
                    if data == r"\.":
                        break
                    if table in REQUIRED:
                        values = [copy_value(v) for v in data.split("\t")]
                        if len(values) != len(columns):
                            raise ProcessError(f"CPIC {table}: COPY column count mismatch.")
                        tables[table].append(dict(zip(columns, values, strict=True)))
                else:
                    raise ProcessError("Truncated CPIC COPY block.")
            elif text.startswith("INSERT INTO cpic."):
                if mode != "inserts":
                    raise ProcessError("INSERT in COPY dump.")
                statement = _statements(lines, line)
                match = _INSERT.fullmatch(statement)
                if match is None:
                    raise ProcessError("Malformed CPIC INSERT statement.")
                table = match[1]
                seen.add(table)
                if table in REQUIRED:
                    columns = _columns(table, match[2])
                    values = _insert_values(match[3])
                    if len(values) != len(columns):
                        raise ProcessError(f"CPIC {table}: INSERT column count mismatch.")
                    tables[table].append(dict(zip(columns, values, strict=True)))
    missing = set(REQUIRED) - (copied if mode == "copy" else seen)
    if missing:
        raise ProcessError(f"CPIC dump lacks required tables: {sorted(missing)}.")
    return tables
