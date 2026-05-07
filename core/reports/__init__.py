"""RadioAI Studio Pro — report generators.

Each report module exposes a ``generate_*_report(...)`` callable that
writes a PDF to disk and returns the resulting ``pathlib.Path``. UI
hooks live in ``ui/`` and call into here.
"""

from core.reports.spot_play_report import (
    generate_spot_play_report,
    SpotPlayReportError,
    REPORT_MODE_ACTUAL,
    REPORT_MODE_SCHEDULED,
    DEFAULT_REPORT_DIR,
)

__all__ = [
    "generate_spot_play_report",
    "SpotPlayReportError",
    "REPORT_MODE_ACTUAL",
    "REPORT_MODE_SCHEDULED",
    "DEFAULT_REPORT_DIR",
]
