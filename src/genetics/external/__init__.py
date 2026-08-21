"""Subprocess wrappers for the external programs the pipeline shells out to.

AGENTS.md 4.9 is the reason this package exists at all. The standard Python genomics
stack is htslib-backed and does not run on Windows, which is the primary development
platform, so the work that would normally be done by ``pysam`` or ``cyvcf2`` is pushed
into native binaries instead: PLINK 2 for format conversion, LD pruning, PCA projection,
``--score`` and ``--homozyg``; Beagle for phasing and imputation; R for HIBAG.

Each wrapper owns one program. They build argument lists, never command strings, and they
surface a failure as an exception carrying the tool's own error text rather than a bare
exit code -- the two things a caller cannot reconstruct afterwards.
"""

from __future__ import annotations
