"""Where the vendored front-end assets live, and what they are (roadmap M4.4).

``static/`` deliberately contains **no Python**. It is mounted wholesale by
:func:`genetics.web.app.create_app`, so anything in it is fetchable over HTTP -- and an
``__init__.py`` sitting there would publish this project's source, and its ``__pycache__``
the compiled form, from the one directory whose entire contents are handed to a browser.
Nothing there is secret, which is exactly why it would never have been noticed. So the
paths are resolved from here, one directory up, and the served tree holds only files meant
to be served.

The assets themselves are committed rather than fetched. ``static/vendor/VENDOR.yaml``
carries the reasoning along with each version, source URL, digest and licence; this module
is only the locator, needed because two callers want it -- the app mounts the directory and
the tests scan it.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import yaml

STATIC_DIR: Final[Path] = Path(__file__).resolve().parent / "static"
"""Root of the served static tree. Everything under it is reachable at ``/static/...``."""

VENDOR_DIR: Final[Path] = STATIC_DIR / "vendor"

VENDOR_MANIFEST: Final[Path] = Path(__file__).resolve().parent / "vendor.yaml"
"""Pins each vendored asset's version, source URL, sha256 and licence.

Ships inside the package rather than under ``data/`` so an *installed* wheel can be audited
(M15.4) without the checkout it was built from -- but deliberately **not** inside
``static/``, for the same reason there is no ``__init__.py`` there. Everything in that
directory is handed to a browser, and this file exists to record where each asset was
downloaded from: it is the one file in the project whose whole job is to contain external
URLs, and leaving it in the served tree would have meant the "no external URL in any static
asset" test had to carve out an exception on its first day.
"""


class VendorManifestError(ValueError):
    """Raised when the vendor manifest is missing, malformed, or disagrees with the disk."""


@dataclass(frozen=True)
class VendoredAsset:
    """One third-party file, as the manifest describes it."""

    id: str
    name: str
    version: str
    filename: str
    sha256: str
    size_bytes: int
    license: str
    license_file: str
    source_url: str
    homepage: str

    @property
    def path(self) -> Path:
        return VENDOR_DIR / self.filename

    @property
    def license_path(self) -> Path:
        return VENDOR_DIR / self.license_file


_REQUIRED: Final[tuple[str, ...]] = (
    "id",
    "name",
    "version",
    "filename",
    "sha256",
    "size_bytes",
    "license",
    "license_file",
    "source_url",
    "homepage",
)


def load_vendor_manifest(path: Path | None = None) -> tuple[VendoredAsset, ...]:
    """Read the vendor manifest. Raises rather than degrading.

    Unlike the run store, which reports damage as a row, this is committed configuration in
    the same tree as the code: a manifest that will not parse is a broken checkout, not a
    user's damaged data, and the only useful response is to say so loudly.
    """
    manifest = path or VENDOR_MANIFEST
    if not manifest.is_file():
        raise VendorManifestError(f"no vendor manifest at {manifest}")
    raw: Any = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise VendorManifestError(f"{manifest}: expected a mapping at the top level")

    entries = raw.get("assets")
    if not isinstance(entries, list) or not entries:
        raise VendorManifestError(f"{manifest}: 'assets' must be a non-empty list")

    assets: list[VendoredAsset] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise VendorManifestError(f"{manifest}: assets[{index}] is not a mapping")
        missing = [key for key in _REQUIRED if key not in entry]
        if missing:
            raise VendorManifestError(
                f"{manifest}: assets[{index}] is missing {', '.join(missing)}. Every field "
                "is mandatory -- an asset with no digest is an asset nothing verifies, and "
                "one with no licence is one the M15.4 audit cannot clear."
            )
        assets.append(VendoredAsset(**{key: entry[key] for key in _REQUIRED}))
    return tuple(assets)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_vendored_assets(path: Path | None = None) -> Iterator[str]:
    """Yield one message per disagreement between the manifest and the files on disk.

    An empty iterator means every pinned asset is present and byte-identical to what was
    downloaded. This is the half of the pinning story that runs **offline**: re-downloading
    to compare would need the network on every commit, while the question that actually
    matters day to day -- has anything here been edited, truncated or swapped -- is
    answerable from the checkout alone.
    """
    for asset in load_vendor_manifest(path):
        if not asset.path.is_file():
            yield f"{asset.id}: {asset.filename} is pinned but not present"
            continue
        actual = digest(asset.path)
        if actual != asset.sha256:
            yield (
                f"{asset.id}: {asset.filename} does not match its pin "
                f"(expected {asset.sha256}, got {actual})"
            )
        size = asset.path.stat().st_size
        if size != asset.size_bytes:
            yield f"{asset.id}: {asset.filename} is {size} bytes, manifest says {asset.size_bytes}"
        if not asset.license_path.is_file():
            yield (
                f"{asset.id}: licence text {asset.license_file} is missing. {asset.license} "
                "requires the notice to travel with the code."
            )
        elif not asset.license_path.read_text(encoding="utf-8").strip():
            yield f"{asset.id}: licence text {asset.license_file} is empty"


__all__ = [
    "STATIC_DIR",
    "VENDOR_DIR",
    "VENDOR_MANIFEST",
    "VendorManifestError",
    "VendoredAsset",
    "load_vendor_manifest",
    "verify_vendored_assets",
]
