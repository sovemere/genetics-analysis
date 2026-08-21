"""PLINK 2 subprocess wrapper (roadmap M5.1).

PLINK 2 is the workhorse AGENTS.md 4.9 chose to keep htslib off the dependency list, so
almost every milestone from M5 on runs through this module: pgen conversion (M5.2), the
reference PCA and its projection (M5.3, M5.4), ROH (M6.1) and ``--score`` for polygenic
scores (M9.2). Four decisions here are load-bearing.

**The pinned build is verified before anything runs.** ``discover()`` does not merely find
a program called ``plink2``; it runs the version probe from ``data/tools.yaml`` and refuses
a build that reports anything else. AGENTS.md 4.9 pins the exact build because PLINK 2 is
alpha and its behaviour moves between them, and a wrapper that executed whatever happened
to be on ``PATH`` would quietly undo that pin -- producing ancestry coordinates from an
untested binary, which look exactly like ancestry coordinates from the pinned one. The
check costs one subprocess per :class:`Plink2` instance.

**Arguments are a list, never a string, and ``--out`` is injected rather than accepted.**
``shell=True`` is never used. ``--out`` is the flag that decides where genotype-derived
output lands, so leaving it to each call site would make "where did the pgen go" a question
with as many answers as there are callers; passing it in ``args`` is refused outright.

**A non-zero exit raises, and the exception carries PLINK's own words.** PLINK 2 writes its
error to stderr and exits with a code that names a category (3 for an unreadable file, 8
for a bad flag, 13 for an empty input) but not a cause. Those codes were read off the
pinned build, not guessed. Surfacing only the code would leave every caller re-deriving
"Error: No variants in --vcf file." from ``returncode == 13``.

**The log's header is deliberately not surfaced.** PLINK writes ``<out>.log`` beside its
output, and that log opens with the machine's hostname and working directory. ``.gitignore``
blocks ``*.log`` so it cannot be committed, but an exception message travels further than a
file does -- into a terminal, an issue comment, a bug report -- so only the ``Error:`` and
``Warning:`` blocks are read out of it, and those are passed through
:func:`genetics.privacy.redact` in case a malformed-input error quotes the offending line.

**No timeout by default.** M5.3's reference PCA and M8's imputation legitimately run for
hours, and a wrapper-level default would be a guess whose only effect is to kill the
longest, most expensive step in the pipeline. Callers that know their budget pass one; the
version probe, which is the one call whose duration is knowable, has its own.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from genetics.paths import tools_dir
from genetics.privacy import NoGenotypeRepr, redact
from genetics.refs import tools

__all__ = [
    "PLINK2_TOOL_ID",
    "Plink2",
    "Plink2Error",
    "Plink2NotFoundError",
    "Plink2ResultInfo",
    "Plink2RunError",
    "Plink2VersionError",
]

PLINK2_TOOL_ID = "plink2"

_WRAP_COLUMN = 79
"""Where the pinned build hard-wraps its messages, measured rather than assumed: the
warning "Warning: Variants are not sorted by position.  Consider rerunning with the" is 74
characters and the next word is 11, so 79 is the only column it can be breaking at."""

_CONTINUATION_MARGIN = 12
"""A line shorter than ``_WRAP_COLUMN - _CONTINUATION_MARGIN`` did not fill the width, so
nothing follows it belonging to the same message. See :func:`_warnings`."""

_MAX_CONTINUATION_LINES = 3
"""Cap on how far a single message may run. PLINK messages are one or two lines; the cap
exists so that a mis-read boundary costs a truncated sentence rather than swallowing the
progress output that follows -- which is full of absolute paths."""

_MESSAGE_STOPS = ("Error:", "Warning:", "Note:")
"""The next message ends the previous one. Recognising this matters: two consecutive
warnings would otherwise be read as one, and the second would vanish into the first."""


class Plink2Error(RuntimeError):
    """Base class for every failure this module reports."""


class Plink2NotFoundError(Plink2Error):
    """No PLINK 2 binary could be located."""


class Plink2VersionError(Plink2Error):
    """A binary was found, but it is not the build ``data/tools.yaml`` pins."""


class Plink2RunError(Plink2Error):
    """PLINK 2 ran and failed.

    Carries the exit code and PLINK's own message. The message has been redacted; see the
    module docstring for why an exception is the wrong place to relay a tool's raw output.
    """

    def __init__(self, message: str, *, returncode: int | None, messages: tuple[str, ...]) -> None:
        super().__init__(message)
        self.returncode = returncode
        self.messages = messages


@dataclass(frozen=True)
class Plink2ResultInfo(NoGenotypeRepr):
    """What one successful invocation produced.

    Inherits the genotype-safe ``__repr__``. PLINK does not normally echo genotypes, but
    ``stdout`` here is whatever the binary chose to print -- a malformed-input error quotes
    the offending line -- and a dataclass repr in a traceback is exactly how that would
    escape.
    """

    _repr_fields: ClassVar[tuple[str, ...]] = ("returncode", "n_warnings")

    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    out_prefix: Path
    log_path: Path
    warnings: tuple[str, ...]

    @property
    def n_warnings(self) -> int:
        return len(self.warnings)


def _warnings(text: str) -> tuple[str, ...]:
    """Pull PLINK's ``Warning:`` lines out of its log, rejoining wrapped ones.

    Warnings have no channel of their own -- unlike errors, which arrive on stderr and are
    relayed verbatim -- so they have to be recovered from a log that interleaves them with
    progress output. The only structure available is PLINK's fixed-width wrapping, so that
    is what this reads: a following line continues the message when the line before it
    filled the width, and ends it when the line before it did not.

    **The heuristic is deliberately biased toward truncating.** Over-reading is the
    expensive mistake: the lines after a warning are ``Writing <absolute path> ... done.``,
    so a message that ran on would put the machine's directory layout into anything that
    logged or displayed a warning. Under-reading costs a trailing clause. Hence the margin
    and the hard cap, and hence the ``... done.`` line never being reachable in practice --
    the line before it is 7 characters long.

    Duplicates are collapsed, keeping first appearance order, since a caller may hand this
    both the log and stdout and PLINK prints each warning to both.
    """
    collected: list[str] = []
    current: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("Warning:"):
            if current:
                collected.append(" ".join(current))
            current = [line]
            continue
        if not current:
            continue
        previous_filled = len(current[-1]) >= _WRAP_COLUMN - _CONTINUATION_MARGIN
        room_left = len(current) < _MAX_CONTINUATION_LINES
        if line and previous_filled and room_left and not line.startswith(_MESSAGE_STOPS):
            current.append(line)
            continue
        collected.append(" ".join(current))
        current = []
    if current:
        collected.append(" ".join(current))
    return tuple(dict.fromkeys(redact(message) for message in collected))


def _error_text(stderr: str, log_text: str) -> str:
    """PLINK's own account of a failure, redacted.

    **Relayed rather than parsed.** The pinned build writes the whole of an error to
    stderr and nothing else there, so quoting it is exact where extraction would not be:
    the second line of "Error: Unrecognized flag ('--not-a-flag')." is "For more info, try
    ..." -- unwrapped, unprefixed, and the only actionable half. A rule that recognised
    continuation lines by their length would drop it.

    The log is the fallback for the case stderr cannot cover: a run killed part-way, where
    the log holds what was flushed and stderr holds nothing. There the ``Error:`` line and
    what follows it is the best available answer, and the header above it -- which opens
    with the machine's hostname and working directory -- is left behind.
    """
    text = stderr.strip()
    if not text:
        index = log_text.find("Error:")
        text = log_text[index:].strip() if index >= 0 else ""
    return redact(text)


@dataclass(frozen=True)
class Plink2:
    """A verified PLINK 2 binary, ready to invoke.

    Construct with :meth:`discover`. The dataclass itself is a plain record so a test can
    build one around a stub without going near the tools manifest, which is what
    ``tests/external/test_plink2.py`` does for every behaviour that is about argument
    building or error surfacing rather than about the pin.

    Not cached at module level on purpose. A process-wide singleton would make the version
    probe run once per interpreter -- attractive -- at the cost of a hidden global that
    every test touching ``GENETICS_DATA_DIR`` would have to reset, and the M0.4 lesson in
    this repository is that a guard nobody can see is a guard nobody notices failing. The
    probe is one subprocess; callers hold the object.
    """

    path: Path
    version: str

    @classmethod
    def discover(
        cls,
        *,
        tools_root: Path | None = None,
        manifest: tools.ToolManifest | None = None,
    ) -> Plink2:
        """Locate PLINK 2 and confirm it is the pinned build.

        Raises :class:`Plink2NotFoundError` when nothing is installed and
        :class:`Plink2VersionError` when the binary present reports a different version.
        The second is a distinct exception rather than a message because they need
        different answers: one is fixed by ``genetics tools install``, the other by
        ``--force`` or by deciding the pin has moved.
        """
        root = tools_root if tools_root is not None else tools_dir()
        tool_manifest = manifest if manifest is not None else tools.load()
        tool = tool_manifest.get(PLINK2_TOOL_ID)

        found = tools.find_executable(PLINK2_TOOL_ID, tools_root=root, tool_id=PLINK2_TOOL_ID)
        if found is None:
            raise Plink2NotFoundError(
                "PLINK 2 is not installed. It is required from M5 on (AGENTS.md 4.9); run "
                "`genetics tools install --only plink2` to fetch the pinned build, or "
                "`genetics doctor` to see what this machine has."
            )

        ok, reported, detail = tools.run_version_check(tool, found)
        if not ok:
            raise Plink2VersionError(
                f"{found} is not the pinned PLINK 2 build: {detail} Reinstall with "
                "`genetics tools install --only plink2 --force`."
            )
        return cls(path=found, version=reported or tool.version)

    def run(
        self,
        args: Sequence[str],
        *,
        out: Path,
        cwd: Path | None = None,
        timeout: float | None = None,
    ) -> Plink2ResultInfo:
        """Invoke PLINK 2 with ``--out out`` appended. Raises on any failure.

        ``out`` is a *prefix*, not a file: PLINK derives ``out.pgen``, ``out.log`` and the
        rest from it, and writes ``out-temporary.*`` alongside them while converting, so its
        parent must be a directory this process may write to. It is created if absent.

        Genotype-derived output belongs outside the checkout (AGENTS.md 1.5). This function
        does not enforce that, because it cannot: M5.3's LD-pruned marker subset is declared
        in the reference manifest and legitimately lands under ``data/references/``, which
        is inside the repo and gitignored wholesale. The choice of workspace stays with the
        caller, where the difference between a sample's genotypes and a reference panel's is
        actually known.
        """
        argv = [str(item) for item in args]
        if any(item == "--out" or item.startswith("--out=") for item in argv):
            raise Plink2Error(
                "--out is set by this wrapper, not by the caller; pass the prefix as the "
                "`out` argument instead so that every invocation's output has one home."
            )

        out.parent.mkdir(parents=True, exist_ok=True)
        command = [str(self.path), *argv, "--out", str(out)]

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(cwd) if cwd is not None else None,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise Plink2RunError(
                f"PLINK 2 did not finish within {timeout}s ({' '.join(argv)}).",
                returncode=None,
                messages=(),
            ) from exc
        except OSError as exc:
            raise Plink2RunError(
                f"could not execute {self.path}: {exc}",
                returncode=None,
                messages=(),
            ) from exc

        log_path = out.with_name(out.name + ".log")
        log_text = _read_log(log_path)

        if completed.returncode != 0:
            detail = _error_text(completed.stderr, log_text)
            raise Plink2RunError(
                f"PLINK 2 failed (exit {completed.returncode}): "
                f"{detail or 'it reported no error text.'}",
                returncode=completed.returncode,
                messages=tuple(detail.splitlines()) if detail else (),
            )

        return Plink2ResultInfo(
            args=tuple(argv),
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            out_prefix=out,
            log_path=log_path,
            warnings=_warnings(log_text or completed.stdout),
        )


def _read_log(path: Path) -> str:
    """The log, or an empty string. Never a reason to fail a run that otherwise succeeded.

    Read with ``errors="replace"``: the log is diagnostic, and a stray byte in it must not
    turn a successful PLINK invocation into a ``UnicodeDecodeError`` from the wrapper.
    """
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
