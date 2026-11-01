"""The PLINK 2 wrapper (roadmap M5.1).

**Nothing here needs PLINK 2 installed**, and that is a requirement rather than a
convenience: CI does not fetch it (the workflow installs no external tools), so a suite
that reached for the real binary would be a suite that skipped on every runner. The stand-in
is a real subprocess -- a launcher that runs a Python script -- so argument passing, exit
codes, stream capture and the log file are all exercised for real; only the program at the
end of the pipe is fake.

The behaviours asserted against the *real* build were verified by hand while M5.1 was
written, and the constants they produced are recorded in the module under test: exit 3 for
an unreadable file, 8 for an unrecognised flag, 13 for an empty input, errors on stderr,
and a log whose header carries the machine's hostname. The fixtures below reproduce that
shape.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from genetics.external import plink2 as mod
from genetics.external.plink2 import (
    DEFAULT_MEMORY_MB,
    MEMORY_ENV,
    Plink2,
    Plink2Error,
    Plink2NotFoundError,
    Plink2ResultInfo,
    Plink2RunError,
    Plink2VersionError,
)
from genetics.external.plink19 import Plink19
from genetics.refs import tools

PINNED = "PLINK v2.0.0-a.7.3 64-bit (8 Aug 2026)"
"""What the build pinned in ``data/tools.yaml`` prints. Written out rather than read from
the manifest -- or from ``conftest`` -- because a test that derived the expected string
from the same place the code reads would pass no matter what either said."""

REAL_LOG_HEADER = """\
PLINK v2.0.0-a.7.3 64-bit (8 Aug 2026)
Options in effect:
  --make-pgen

Hostname: A-MACHINE-NAME
Working directory: C:\\somewhere\\private
Start time: Fri Aug 21 20:10:03 2026
"""
"""The opening of a real log, copied from one. The hostname and working directory are the
reason :func:`genetics.external.plink2._error_text` never relays a log wholesale."""


ECHO_ARGV = """
import sys
print("PLINK v2.0.0-a.7.3 64-bit (8 Aug 2026)")
print("ARGV:" + "|".join(sys.argv[1:]))
"""

VERSION_ONLY = f"""
import sys
print({PINNED!r})
"""

WRONG_VERSION = """
import sys
print("PLINK v2.0.0-a.6.9 64-bit (1 Jan 2020)")
"""


# ---------------------------------------------------------------------------
# discover: the pin is enforced, not merely documented
# ---------------------------------------------------------------------------


def _record(tools_root: Path, binary: Path) -> None:
    """Write the installed-state file the real installer would have written."""
    tools_root.mkdir(parents=True, exist_ok=True)
    state = tools.render_state({"plink2": {"path": str(binary), "version": PINNED}})
    (tools_root / tools.INSTALLED_STATE).write_text(state, encoding="utf-8")


def test_discover_uses_the_path_the_installer_recorded(
    tmp_path: Path, stub_binary: Callable[[str], Path]
) -> None:
    binary = stub_binary(VERSION_ONLY)
    _record(tmp_path / "tools", binary)

    found = Plink2.discover(tools_root=tmp_path / "tools")

    assert found.path == binary
    assert found.version == PINNED


def test_discover_reports_a_missing_install_distinctly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty tools dir and nothing named plink2 on PATH -- the fresh-checkout state.

    ``PATH`` is emptied rather than trusted: a developer who has PLINK 2 installed system
    wide would otherwise watch this test fail for a reason that has nothing to do with the
    behaviour it is describing.
    """
    empty = tmp_path / "nothing"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))

    with pytest.raises(Plink2NotFoundError) as excinfo:
        Plink2.discover(tools_root=tmp_path / "empty")

    assert "genetics tools install" in str(excinfo.value)


def test_discover_refuses_an_unpinned_build(
    tmp_path: Path, stub_binary: Callable[[str], Path]
) -> None:
    """The point of M5.1's version check, and the one behaviour AGENTS.md 4.9 demands.

    A binary that answers to the name is not enough: PLINK 2 is alpha, its behaviour moves
    between builds, and ancestry coordinates from an untested one are indistinguishable
    from ancestry coordinates from the pinned one.
    """
    binary = stub_binary(WRONG_VERSION)
    _record(tmp_path / "tools", binary)

    with pytest.raises(Plink2VersionError) as excinfo:
        Plink2.discover(tools_root=tmp_path / "tools")

    message = str(excinfo.value)
    assert "a.6.9" in message
    assert "--force" in message


def test_discover_raises_rather_than_returning_none_for_a_broken_binary(tmp_path: Path) -> None:
    """A file that exists but cannot run is a version failure, not a missing install."""
    binary = tmp_path / "tools" / "plink2-not-really"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"not a program")
    _record(tmp_path / "tools", binary)

    with pytest.raises(Plink2VersionError):
        Plink2.discover(tools_root=tmp_path / "tools")


# ---------------------------------------------------------------------------
# run: argument building
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("no_memory_override")
def test_run_appends_out_and_preserves_argument_order(
    tmp_path: Path, stub_plink2: Callable[[str], Plink2]
) -> None:
    plink = stub_plink2(ECHO_ARGV)

    result = plink.run(["--vcf", "in.vcf", "--make-pgen", "--sort-vars"], out=tmp_path / "o" / "s")

    argv = next(
        line.removeprefix("ARGV:")
        for line in result.stdout.splitlines()
        if line.startswith("ARGV:")
    ).split("|")
    assert argv[:4] == ["--vcf", "in.vcf", "--make-pgen", "--sort-vars"]
    assert argv[4:6] == ["--memory", str(DEFAULT_MEMORY_MB)]
    assert argv[6] == "--out"
    assert Path(argv[7]) == tmp_path / "o" / "s"
    assert result.args == ("--vcf", "in.vcf", "--make-pgen", "--sort-vars")


def _argv(result: Plink2ResultInfo) -> list[str]:
    return next(
        line.removeprefix("ARGV:")
        for line in result.stdout.splitlines()
        if line.startswith("ARGV:")
    ).split("|")


@pytest.fixture
def no_memory_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(MEMORY_ENV, raising=False)


@pytest.mark.usefixtures("no_memory_override")
def test_the_default_cap_is_4_gib_and_the_pinned_plink_1_9_gets_it_too(
    tmp_path: Path, stub_plink2: Callable[[str], Plink2]
) -> None:
    """Without the flag both pinned builds reserve half of physical memory (2026-11-01)."""
    assert DEFAULT_MEMORY_MB == 4096
    stub = stub_plink2(ECHO_ARGV)
    plink19 = Plink19(path=stub.path, version=stub.version)

    argv = _argv(plink19.run(["--bfile", "x", "--homozyg"], out=tmp_path / "s"))

    assert argv.count("--memory") == 1
    assert argv[argv.index("--memory") + 1] == "4096"


@pytest.mark.usefixtures("no_memory_override")
def test_a_callers_own_memory_flag_is_kept_and_not_doubled(
    tmp_path: Path, stub_plink2: Callable[[str], Plink2]
) -> None:
    """The polygenic engine's ``--score`` sets 1024 itself; that value must reach PLINK."""
    plink = stub_plink2(ECHO_ARGV)

    argv = _argv(plink.run(["--pfile", "x", "--memory", "1024"], out=tmp_path / "s"))

    assert argv.count("--memory") == 1
    assert argv[argv.index("--memory") + 1] == "1024"


def test_the_environment_overrides_the_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_plink2: Callable[[str], Plink2]
) -> None:
    monkeypatch.setenv(MEMORY_ENV, " 12000 ")
    plink = stub_plink2(ECHO_ARGV)

    argv = _argv(plink.run(["--pfile", "x"], out=tmp_path / "s"))

    assert argv[argv.index("--memory") + 1] == "12000"


@pytest.mark.parametrize("bad", ["639", "0", "-4096", "4096.5", "4 GB", "abc", "٤٠٩٦"])
def test_an_unusable_override_is_refused_by_name_before_plink_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad: str, stub_plink2: Callable[[str], Plink2]
) -> None:
    """639 is one below the pinned PLINK 2's floor; the last value is Arabic-Indic digits."""
    monkeypatch.setenv(MEMORY_ENV, bad)
    marker = tmp_path / "ran"
    plink = stub_plink2(f"open({str(marker)!r}, 'w').close()\n")

    with pytest.raises(Plink2Error, match=MEMORY_ENV) as excinfo:
        plink.run(["--pfile", "x"], out=tmp_path / "s")

    assert not isinstance(excinfo.value, Plink2RunError)
    assert not marker.exists()


OUT_OF_MEMORY = """
import sys
sys.stderr.write('Error: Out of memory.  Consider "--pca approx" instead.\\n')
sys.stderr.write("Failed allocation size: 1152000000\\n")
sys.exit(2)
"""
"""The pinned PLINK 2's words and exit code for ``--pca`` beyond its workspace, measured on
``--dummy 12000 3000 --memory 640 --pca 5``. PLINK 1.9 exits 1 with "Error: Out of memory.
The --memory flag may be helpful."; the hint keys on the shared phrase, not the code."""


@pytest.mark.usefixtures("no_memory_override")
def test_running_out_of_the_capped_workspace_names_the_override(
    tmp_path: Path, stub_plink2: Callable[[str], Plink2]
) -> None:
    plink = stub_plink2(OUT_OF_MEMORY)

    with pytest.raises(Plink2RunError) as excinfo:
        plink.run(["--pfile", "x", "--pca", "5"], out=tmp_path / "s")

    message = str(excinfo.value)
    assert excinfo.value.returncode == 2
    assert "Out of memory" in message and "Failed allocation size" in message
    assert f"capped PLINK 2's workspace at {DEFAULT_MEMORY_MB} MiB" in message
    assert MEMORY_ENV in message


@pytest.mark.usefixtures("no_memory_override")
def test_a_callers_own_cap_running_out_gets_no_hint_about_the_wrappers(
    tmp_path: Path, stub_plink2: Callable[[str], Plink2]
) -> None:
    """The variable would not change a value the caller fixed, so naming it would mislead."""
    plink = stub_plink2(OUT_OF_MEMORY)

    with pytest.raises(Plink2RunError) as excinfo:
        plink.run(["--pfile", "x", "--memory", "1024"], out=tmp_path / "s")

    assert "Out of memory" in str(excinfo.value)
    assert MEMORY_ENV not in str(excinfo.value)


@pytest.mark.parametrize("bad", ["--out", "--out=elsewhere"])
def test_run_refuses_an_out_flag_from_the_caller(
    tmp_path: Path, bad: str, stub_plink2: Callable[[str], Plink2]
) -> None:
    """Both spellings, because ``--out=x`` is the one a naive check misses."""
    plink = stub_plink2(ECHO_ARGV)

    with pytest.raises(Plink2Error, match="--out is set by this wrapper"):
        plink.run(["--vcf", "in.vcf", bad], out=tmp_path / "s")


def test_run_creates_the_output_directory(
    tmp_path: Path, stub_plink2: Callable[[str], Plink2]
) -> None:
    """PLINK does not create it, and failing on a missing parent is a needless error."""
    plink = stub_plink2(ECHO_ARGV)
    target = tmp_path / "deep" / "nested" / "prefix"

    plink.run(["--version"], out=target)

    assert target.parent.is_dir()


def test_run_passes_a_prefix_containing_a_space(
    tmp_path: Path, stub_plink2: Callable[[str], Plink2]
) -> None:
    """No shell is involved, so quoting is not this module's problem -- prove it stays so."""
    plink = stub_plink2(ECHO_ARGV)
    target = tmp_path / "a folder" / "run one"

    result = plink.run(["--version"], out=target)

    argv = next(
        line.removeprefix("ARGV:")
        for line in result.stdout.splitlines()
        if line.startswith("ARGV:")
    ).split("|")
    assert Path(argv[-1]) == target


# ---------------------------------------------------------------------------
# run: failure surfacing
# ---------------------------------------------------------------------------


FAILS = """
import sys
sys.stderr.write("Error: Unrecognized flag ('--not-a-flag').\\n")
sys.stderr.write('For more info, try "plink2 --help <flag name>".\\n')
sys.exit(8)
"""


def test_a_failure_carries_plinks_own_words_and_its_exit_code(
    tmp_path: Path, stub_plink2: Callable[[str], Plink2]
) -> None:
    plink = stub_plink2(FAILS)

    with pytest.raises(Plink2RunError) as excinfo:
        plink.run(["--not-a-flag"], out=tmp_path / "s")

    assert excinfo.value.returncode == 8
    message = str(excinfo.value)
    assert "Unrecognized flag" in message
    # The second line is unwrapped and unprefixed, and it is the actionable half. A rule
    # that recognised continuations by line length would drop it, which is why errors are
    # relayed from stderr rather than parsed.
    assert "For more info" in message


def test_a_failure_with_a_silent_stderr_falls_back_to_the_log_without_its_header(
    tmp_path: Path, stub_plink2: Callable[[str], Plink2]
) -> None:
    """The header names the machine and the working directory; the exception must not."""
    log_writer = f"""
import sys
argv = sys.argv[1:]
prefix = argv[argv.index("--out") + 1]
open(prefix + ".log", "w").write({REAL_LOG_HEADER!r} + "\\nError: No variants in --vcf file.\\n")
sys.exit(13)
"""
    plink = stub_plink2(log_writer)

    with pytest.raises(Plink2RunError) as excinfo:
        plink.run(["--vcf", "empty.vcf"], out=tmp_path / "s")

    message = str(excinfo.value)
    assert "No variants in --vcf file" in message
    assert excinfo.value.returncode == 13
    assert "A-MACHINE-NAME" not in message
    assert "somewhere" not in message


def test_a_genotype_quoted_in_an_error_is_redacted(
    tmp_path: Path, stub_plink2: Callable[[str], Plink2]
) -> None:
    """A malformed-input error quotes the offending line, and an exception travels far."""
    leaky = """
import sys
sys.stderr.write("Error: Line 3 of the file is malformed: rs1234\\t1\\t752566\\tA\\tG\\n")
sys.exit(2)
"""
    plink = stub_plink2(leaky)

    with pytest.raises(Plink2RunError) as excinfo:
        plink.run(["--vcf", "bad.vcf"], out=tmp_path / "s")

    assert "redacted" in str(excinfo.value)
    assert "rs1234\t1\t752566" not in str(excinfo.value)


def test_a_timeout_is_reported_as_a_run_failure(
    tmp_path: Path, stub_plink2: Callable[[str], Plink2]
) -> None:
    plink = stub_plink2("import time\ntime.sleep(30)\n")

    with pytest.raises(Plink2RunError) as excinfo:
        plink.run(["--pca"], out=tmp_path / "s", timeout=0.5)

    assert excinfo.value.returncode is None
    assert "did not finish" in str(excinfo.value)


def test_an_unexecutable_binary_is_reported_rather_than_raising_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_plink2: Callable[[str], Plink2]
) -> None:
    plink = stub_plink2(ECHO_ARGV)

    def boom(*args: object, **kwargs: object) -> object:
        raise OSError("no such device")

    monkeypatch.setattr(subprocess, "run", boom)

    with pytest.raises(Plink2RunError) as excinfo:
        plink.run(["--version"], out=tmp_path / "s")

    assert excinfo.value.returncode is None
    assert "no such device" in str(excinfo.value)


# ---------------------------------------------------------------------------
# run: warnings
# ---------------------------------------------------------------------------


WRAPPED_WARNING = (
    "Note: No phenotype data present.\n"
    "Warning: Variants are not sorted by position.  Consider rerunning with the\n"
    "--sort-vars flag added to remedy this.\n"
    "Writing\n"
    "C:\\Users\\somebody\\AppData\\Local\\genetics-analysis\\cache\\plink\\sample.psam\n"
    "... done.\n"
)
"""Copied from a real log. The absent blank line after the warning is the whole problem:
the first implementation ran on and swallowed the path."""


def test_a_wrapped_warning_is_rejoined_and_stops_before_the_progress_output(
    tmp_path: Path, stub_plink2: Callable[[str], Plink2]
) -> None:
    writer = f"""
import sys
argv = sys.argv[1:]
prefix = argv[argv.index("--out") + 1]
open(prefix + ".log", "w").write({WRAPPED_WARNING!r})
"""
    plink = stub_plink2(writer)

    result = plink.run(["--make-pgen"], out=tmp_path / "s")

    assert result.warnings == (
        "Warning: Variants are not sorted by position.  Consider rerunning with the "
        "--sort-vars flag added to remedy this.",
    )
    # The regression this guards: the progress lines that follow are absolute paths, so a
    # message that ran on would put the machine's directory layout into every warning.
    assert not any("somebody" in warning for warning in result.warnings)


def test_two_consecutive_warnings_stay_two(
    tmp_path: Path, stub_plink2: Callable[[str], Plink2]
) -> None:
    """Without a stop on the next message prefix, the second vanishes into the first."""
    text = "Warning: first thing happened.\nWarning: second thing happened.\n"
    writer = f"""
import sys
argv = sys.argv[1:]
prefix = argv[argv.index("--out") + 1]
open(prefix + ".log", "w").write({text!r})
"""
    plink = stub_plink2(writer)

    result = plink.run(["--make-pgen"], out=tmp_path / "s")

    assert result.warnings == (
        "Warning: first thing happened.",
        "Warning: second thing happened.",
    )


def test_a_warning_printed_to_both_stdout_and_the_log_is_reported_once(
    tmp_path: Path, stub_plink2: Callable[[str], Plink2]
) -> None:
    writer = """
import sys
argv = sys.argv[1:]
prefix = argv[argv.index("--out") + 1]
text = "Warning: something to note.\\n"
open(prefix + ".log", "w").write(text)
sys.stdout.write(text)
"""
    plink = stub_plink2(writer)

    result = plink.run(["--make-pgen"], out=tmp_path / "s")

    assert result.warnings == ("Warning: something to note.",)


def test_a_run_with_no_log_still_succeeds(
    tmp_path: Path, stub_plink2: Callable[[str], Plink2]
) -> None:
    """The log is diagnostic. Its absence must not turn a successful run into a failure."""
    plink = stub_plink2(ECHO_ARGV)

    result = plink.run(["--version"], out=tmp_path / "s")

    assert result.returncode == 0
    assert result.warnings == ()
    assert not result.log_path.exists()


# ---------------------------------------------------------------------------
# Privacy
# ---------------------------------------------------------------------------


@pytest.mark.privacy
def test_the_result_repr_does_not_print_captured_output(
    tmp_path: Path, stub_plink2: Callable[[str], Plink2]
) -> None:
    """``stdout`` is whatever the binary chose to print, and a repr lands in tracebacks."""
    leaky = """
print("rs1234\\t1\\t752566\\tA\\tG")
"""
    plink = stub_plink2(leaky)

    result = plink.run(["--version"], out=tmp_path / "s")

    assert "752566" in result.stdout
    assert "752566" not in repr(result)
    assert "rs1234" not in repr(result)


def test_wrapped_error_text_is_never_read_out_of_a_log_header() -> None:
    """A unit check on the fallback, so the rule survives a refactor of :meth:`Plink2.run`."""
    extracted = mod._error_text("", REAL_LOG_HEADER + "\nError: something went wrong.\n")

    assert extracted.startswith("Error: something went wrong.")
    assert "Hostname" not in extracted
