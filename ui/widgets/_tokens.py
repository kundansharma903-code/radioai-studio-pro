"""
Design tokens shared by all premium widgets.
Extracted from Figma — DO NOT improvise these values.
"""

from PyQt6.QtGui import QFont, QColor

# ── Color palette ─────────────────────────────────────────────────────────
BG_BASE        = "#070812"
BG_DARK        = "#0a0c16"
BG_PANEL       = "#0f1120"
BG_CARD        = "#0e1020"
BG_CARD_DK     = "#070912"
BG_ELEVATED    = "#131626"
BG_PURPLE_DK   = "#1e1535"

TEXT_PRI       = "#f1f5ff"
TEXT_SEC       = "#8891b8"
TEXT_MUTED     = "#454d6d"
TEXT_DIM       = "#252840"

BORDER_RGBA    = "rgba(255,255,255,0.06)"
BORDER_HOVER   = "rgba(255,255,255,0.12)"

# Accent colors (main + light variant)
CYAN           = "#06b6d4";  CYAN_LIGHT   = "#22d3ee"
PURPLE         = "#8b5cf6";  PURPLE_LIGHT = "#a78bfa";  PURPLE_DARK = "#7c3aed"
GREEN          = "#10b981";  GREEN_LIGHT  = "#34d399"
AMBER          = "#f59e0b";  AMBER_LIGHT  = "#fbbf24"
RED            = "#f43f5e";  RED_LIGHT    = "#fb7185"
PINK           = "#ec4899";  PINK_LIGHT   = "#f472b6"
TEAL           = "#14b8a6";  TEAL_LIGHT   = "#2dd4bf"

# ── Font helpers ──────────────────────────────────────────────────────────
INTER_FAMILY      = "Inter Variable"
ROBOTO_MONO       = "Roboto Mono"


def _font(family: str, size: int, weight: QFont.Weight,
          letter_spacing: float = 0.0) -> QFont:
    f = QFont(family)
    f.setPixelSize(size)
    f.setWeight(weight)
    if letter_spacing != 0.0:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, letter_spacing)
    return f


def inter(size: int, weight: QFont.Weight = QFont.Weight.Normal,
          letter_spacing: float = 0.0) -> QFont:
    return _font(INTER_FAMILY, size, weight, letter_spacing)


def mono(size: int, bold: bool = True, letter_spacing: float = 0.0) -> QFont:
    w = QFont.Weight.Bold if bold else QFont.Weight.Normal
    return _font(ROBOTO_MONO, size, w, letter_spacing)


# ── Helpers ───────────────────────────────────────────────────────────────

def rgba(hex_color: str, alpha: float) -> str:
    """Convert '#RRGGBB' + float alpha to 'rgba(r,g,b,a)'."""
    h = hex_color.lstrip('#')
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def qcolor(hex_color: str, alpha_0_255: int = 255) -> QColor:
    """Build a QColor from hex with optional alpha (0-255)."""
    c = QColor(hex_color)
    if alpha_0_255 != 255:
        c.setAlpha(alpha_0_255)
    return c
