"""Metadatos de release embebidos en el paquete Azure.

`build-azure-package.ps1` sobrescribe este archivo en staging con BUILD_ID/COMMIT
deterministas. En desarrollo local los defaults permiten tests sin empaquetar.
"""

from __future__ import annotations

BUILD_ID = "dev-local"
COMMIT = "unknown"
FLAVOR = "local"
