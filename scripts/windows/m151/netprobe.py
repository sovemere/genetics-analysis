"""Prove the M15.1 network block from the run's own interpreters, contacting no host.

Each probe connects to 192.0.2.1 (TEST-NET-1, RFC 5737), which is routed nowhere. With
the block on, Windows Firewall refuses the connection at once (WinError 10013); without
it the attempt can only time out. So the answer distinguishes the two states without a
packet reaching any real machine, even when the block is missing.

Probes Python (the pipeline's process and a child of it) and Rscript (HIBAG). Java and
PLINK are not probed: the block refuses every program but one, so a probe of each would
test the same rule. Prints JSON; exits 0 only when every probe was refused.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time

TARGET = ("192.0.2.1", 80)
TIMEOUT = 5.0
REFUSED_WITHIN = 2.0
"""Seconds. A firewall refusal is immediate; anything slower is a timeout, not the block."""


def python_probe() -> str:
    try:
        socket.create_connection(TARGET, timeout=TIMEOUT).close()
    except OSError as e:
        if getattr(e, "winerror", None) == 10013:
            return "refused"
        return f"not refused: {type(e).__name__}"
    return "not refused: connected"


def rscript_probe() -> str:
    rscript = os.environ.get("GENETICS_RSCRIPT") or shutil.which("Rscript")
    if not rscript:
        return "not run: Rscript not found"
    code = (
        f"tryCatch({{close(socketConnection('{TARGET[0]}', {TARGET[1]}, blocking=TRUE, "
        f"open='r+', timeout={int(TIMEOUT)})); cat('connected')}}, "
        "error=function(e) cat('failed'), warning=function(w) cat('failed'))"
    )
    start = time.monotonic()
    done = subprocess.run([rscript, "-e", code], capture_output=True, text=True, timeout=60)
    elapsed = time.monotonic() - start
    if done.stdout.strip() == "failed":
        # R's startup is included in the elapsed time; a refusal still lands well
        # inside the connection timeout, which an unblocked attempt must run out.
        return "refused" if elapsed < TIMEOUT else f"not refused: failed after {elapsed:.1f}s"
    return f"not refused: {done.stdout.strip() or done.stderr.strip()[:80]}"


def main() -> int:
    if sys.argv[1:] == ["--child"]:
        print(python_probe())
        return 0
    child = subprocess.run(
        [sys.executable, "-I", __file__, "--child"], capture_output=True, text=True, timeout=60
    )
    result = {
        "python": python_probe(),
        "python_child": child.stdout.strip() or f"not refused: exit {child.returncode}",
        "rscript": rscript_probe(),
    }
    print(json.dumps(result))
    return 0 if all(v == "refused" for v in result.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
