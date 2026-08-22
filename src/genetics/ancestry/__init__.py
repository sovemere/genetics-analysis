"""Ancestry inference (roadmap M5).

The reference PCA and everything that reads it: the eigenvector build (M5.3), the
sample's projection onto it (M5.4), and the coordinates and population distances the
cards render (M5.5). Kept out of :mod:`genetics.refs` on purpose -- what lives there is a
function of published data alone and lands under ``data/references/``, whereas everything
here takes the sample's own marker list as an input and therefore belongs in
``cache_dir()`` (AGENTS.md 1.5).
"""

from __future__ import annotations
