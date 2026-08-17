"""The local dashboard (roadmap M4).

:mod:`genetics.web.config` decides where the app listens and who it answers;
:mod:`genetics.web.app` builds it. Nothing under this package makes an outbound request,
and a structural test in ``tests/web/`` asserts that rather than trusting it.
"""

from genetics.web.app import SECURITY_HEADERS, create_app
from genetics.web.assets import (
    STATIC_DIR,
    VENDOR_DIR,
    VENDOR_MANIFEST,
    VendoredAsset,
    VendorManifestError,
    load_vendor_manifest,
    verify_vendored_assets,
)
from genetics.web.config import DEFAULT_HOST, DEFAULT_PORT, WebConfig, WebConfigError

__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "SECURITY_HEADERS",
    "STATIC_DIR",
    "VENDOR_DIR",
    "VENDOR_MANIFEST",
    "VendorManifestError",
    "VendoredAsset",
    "WebConfig",
    "WebConfigError",
    "create_app",
    "load_vendor_manifest",
    "verify_vendored_assets",
]
