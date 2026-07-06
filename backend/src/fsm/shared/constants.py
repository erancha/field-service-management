"""The product brand name, defined once as the single source of the display identity.

A dependency-free constant safe for any layer to import, including pure domain code — the sole
part of the shared kernel the import contract exposes to a context's inner layers.
"""
from __future__ import annotations

BRAND = "Field Service Management"
