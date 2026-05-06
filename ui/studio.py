"""
RadioAI Studio Pro — Studio screen.

Transitional shim — re-exports the legacy Phase D Studio class so
``from ui.studio import Studio`` (used by ``ui.main_window`` + tests)
keeps working between the rename commit and the rebuild commit.

Will be replaced by the rebuilt premium-design screen (Figma 312:2).
After the rebuild lands, ``ui/studio_legacy.py`` stays around as a
rollback path until Kavish manually verifies on-air audio routing
and explicitly OKs deletion.
"""

from ui.studio_legacy import Studio  # noqa: F401  (re-export)

__all__ = ["Studio"]
