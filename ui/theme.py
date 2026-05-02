"""RadioAI Studio Pro — Theme & Design System

All colors, fonts, and layout constants from the Figma design system.
Provides QSS stylesheet generation for consistent styling across all screens.
"""

from PyQt6.QtGui import QFont, QFontDatabase, QColor, QPainter, QRadialGradient, QPen
from PyQt6.QtWidgets import QWidget, QGraphicsDropShadowEffect
from PyQt6.QtCore import Qt, QPointF
import os


# ── Colors ──────────────────────────────────────────────────────────────────

COLORS = {
    "bg":    "#070812",
    "surf":  "#0A0C18",
    "panel": "#0E1020",
    "card":  "#131626",
    "card2": "#181B2E",
    "b1":    "#1C1F38",
    "b2":    "#252848",
    "p1":    "#8B5CF6",
    "p2":    "#A78BFA",
    "p3":    "#6D28D9",
    "p4":    "#1E1535",
    "gn":    "#10B981",
    "gnD":   "#052E16",
    "am":    "#F59E0B",
    "amD":   "#2D1A00",
    "rs":    "#F43F5E",
    "rsD":   "#1F0A12",
    "cy":    "#06B6D4",
    "cyD":   "#083344",
    "tl":    "#14B8A6",
    "tlD":   "#042F2A",
    "pk":    "#EC4899",
    "pkD":   "#3B0020",
    "t1":    "#F1F5FF",
    "t2":    "#8891B8",
    "t3":    "#454D6D",
    "t4":    "#252840",
}

LIBRARY_COLORS = {
    "songs":    "#8B5CF6",
    "spots":    "#10B981",
    "jingles":  "#F59E0B",
    "instant":  "#06B6D4",
    "sweepers": "#F43F5E",
    "stitcher": "#14B8A6",
}

# ── Layout Constants ────────────────────────────────────────────────────────

LAYOUT = {
    "header_h":        72,
    "status_bar_h":    50,
    "left_panel_w":    220,
    "left_panel_w_lg": 240,
    "row_h_sm":        24,
    "row_h_md":        30,
    "row_h_lg":        36,
    "border_radius":   6,
    "border_radius_lg": 10,
}


# ── Font Helpers ────────────────────────────────────────────────────────────

_fonts_loaded = False


def load_fonts():
    """Load custom fonts from assets/fonts/. Call once at startup."""
    global _fonts_loaded
    if _fonts_loaded:
        return
    fonts_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "fonts")
    if os.path.isdir(fonts_dir):
        for fname in os.listdir(fonts_dir):
            if fname.endswith((".ttf", ".otf")):
                QFontDatabase.addApplicationFont(os.path.join(fonts_dir, fname))
    _fonts_loaded = True


def font(weight="regular", size=13):
    """Return a QFont with the specified weight and size.

    weight: 'regular', 'medium', 'semibold', 'bold', 'mono', 'mono_bold'
    """
    weight_map = {
        "regular":   ("Inter", QFont.Weight.Normal),
        "medium":    ("Inter", QFont.Weight.Medium),
        "semibold":  ("Inter", QFont.Weight.DemiBold),
        "bold":      ("Inter", QFont.Weight.Bold),
        "mono":      ("Roboto Mono", QFont.Weight.Normal),
        "mono_bold": ("Roboto Mono", QFont.Weight.Bold),
    }
    family, qweight = weight_map.get(weight, weight_map["regular"])
    f = QFont(family, size)
    f.setWeight(qweight)
    return f


# ── Color Helpers ───────────────────────────────────────────────────────────

def color(key):
    """Return a QColor from a COLORS key."""
    return QColor(COLORS[key])


def rgba(hex_color, alpha):
    """Return 'rgba(r, g, b, a)' string from hex and alpha (0.0–1.0)."""
    c = QColor(hex_color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha})"


def lighten(hex_color, amount=30):
    """Lighten a hex color by the given amount."""
    c = QColor(hex_color)
    return c.lighter(100 + amount).name()


def darken(hex_color, amount=30):
    """Darken a hex color by the given amount."""
    c = QColor(hex_color)
    return c.darker(100 + amount).name()


# ── Global QSS Stylesheet ──────────────────────────────────────────────────

def get_global_stylesheet():
    """Return the master QSS stylesheet for the entire application."""
    return f"""
    /* ── Global Reset ── */
    QWidget {{
        background-color: {COLORS['bg']};
        color: {COLORS['t1']};
        font-family: "Inter";
        font-size: 13px;
        border: none;
    }}

    /* ── Scrollbars ── */
    QScrollBar:vertical {{
        background: {COLORS['bg']};
        width: 8px;
        margin: 0;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical {{
        background: {COLORS['b2']};
        min-height: 30px;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {COLORS['t3']};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollBar:horizontal {{
        background: {COLORS['bg']};
        height: 8px;
        margin: 0;
        border-radius: 4px;
    }}
    QScrollBar::handle:horizontal {{
        background: {COLORS['b2']};
        min-width: 30px;
        border-radius: 4px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: {COLORS['t3']};
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0;
    }}

    /* ── Line Edits ── */
    QLineEdit {{
        background-color: {COLORS['card']};
        border: 1px solid {COLORS['b1']};
        border-radius: {LAYOUT['border_radius']}px;
        padding: 6px 10px;
        color: {COLORS['t1']};
        font-size: 13px;
    }}
    QLineEdit:focus {{
        border-color: {COLORS['p1']};
    }}

    /* ── Buttons ── */
    QPushButton {{
        background-color: {COLORS['card2']};
        color: {COLORS['t1']};
        border: 1px solid {COLORS['b1']};
        border-radius: {LAYOUT['border_radius']}px;
        padding: 6px 16px;
        font-size: 13px;
        font-weight: 500;
    }}
    QPushButton:hover {{
        background-color: {COLORS['b1']};
        border-color: {COLORS['b2']};
    }}
    QPushButton:pressed {{
        background-color: {COLORS['b2']};
    }}

    /* ── ComboBox ── */
    QComboBox {{
        background-color: {COLORS['card']};
        border: 1px solid {COLORS['b1']};
        border-radius: {LAYOUT['border_radius']}px;
        padding: 6px 10px;
        color: {COLORS['t1']};
        font-size: 13px;
    }}
    QComboBox::drop-down {{
        border: none;
        width: 24px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {COLORS['card']};
        border: 1px solid {COLORS['b1']};
        color: {COLORS['t1']};
        selection-background-color: {COLORS['p3']};
    }}

    /* ── Tables ── */
    QTableWidget, QTableView {{
        background-color: {COLORS['panel']};
        alternate-background-color: {COLORS['card']};
        border: 1px solid {COLORS['b1']};
        border-radius: {LAYOUT['border_radius']}px;
        gridline-color: {COLORS['b1']};
        color: {COLORS['t1']};
        font-size: 12px;
    }}
    QHeaderView::section {{
        background-color: {COLORS['card']};
        color: {COLORS['t2']};
        border: none;
        border-bottom: 1px solid {COLORS['b1']};
        padding: 6px 8px;
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
    }}

    /* ── Tab Widget ── */
    QTabWidget::pane {{
        border: none;
        background-color: transparent;
    }}
    QTabBar::tab {{
        background-color: transparent;
        color: {COLORS['t2']};
        padding: 10px 20px;
        font-size: 14px;
        font-weight: 500;
        border: none;
        border-bottom: 2px solid transparent;
    }}
    QTabBar::tab:selected {{
        color: {COLORS['p1']};
        border-bottom-color: {COLORS['p1']};
    }}
    QTabBar::tab:hover {{
        color: {COLORS['t1']};
    }}

    /* ── Tooltips ── */
    QToolTip {{
        background-color: {COLORS['card2']};
        color: {COLORS['t1']};
        border: 1px solid {COLORS['b1']};
        border-radius: 4px;
        padding: 4px 8px;
        font-size: 12px;
    }}

    /* ── Splitter ── */
    QSplitter::handle {{
        background-color: {COLORS['b1']};
    }}
    QSplitter::handle:horizontal {{
        width: 1px;
    }}
    QSplitter::handle:vertical {{
        height: 1px;
    }}

    /* ── GroupBox ── */
    QGroupBox {{
        border: 1px solid {COLORS['b1']};
        border-radius: {LAYOUT['border_radius']}px;
        margin-top: 12px;
        padding-top: 16px;
        color: {COLORS['t2']};
        font-size: 12px;
        font-weight: 600;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 6px;
    }}

    /* ── SpinBox ── */
    QSpinBox, QDoubleSpinBox {{
        background-color: {COLORS['card']};
        border: 1px solid {COLORS['b1']};
        border-radius: {LAYOUT['border_radius']}px;
        padding: 4px 8px;
        color: {COLORS['t1']};
    }}

    /* ── CheckBox ── */
    QCheckBox {{
        color: {COLORS['t1']};
        spacing: 8px;
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border-radius: 3px;
        border: 1px solid {COLORS['b2']};
        background-color: {COLORS['card']};
    }}
    QCheckBox::indicator:checked {{
        background-color: {COLORS['p1']};
        border-color: {COLORS['p1']};
    }}

    /* ── Slider ── */
    QSlider::groove:horizontal {{
        background: {COLORS['b1']};
        height: 4px;
        border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        background: {COLORS['p1']};
        width: 14px;
        height: 14px;
        margin: -5px 0;
        border-radius: 7px;
    }}

    /* ── Progress Bar ── */
    QProgressBar {{
        background-color: {COLORS['b1']};
        border-radius: 3px;
        text-align: center;
        color: {COLORS['t2']};
        font-size: 10px;
        max-height: 6px;
    }}
    QProgressBar::chunk {{
        background-color: {COLORS['p1']};
        border-radius: 3px;
    }}

    /* ── Menu ── */
    QMenuBar {{
        background-color: {COLORS['bg']};
        color: {COLORS['t2']};
    }}
    QMenu {{
        background-color: {COLORS['card']};
        border: 1px solid {COLORS['b1']};
        color: {COLORS['t1']};
        padding: 4px 0;
    }}
    QMenu::item:selected {{
        background-color: {COLORS['p3']};
    }}
    """


# ── Component Style Helpers ────────────────────────────────────────────────

def card_style(accent_color=None):
    """QSS for a library card or panel card."""
    border = accent_color or COLORS["b1"]
    return f"""
        background-color: {COLORS['card']};
        border: 1px solid {border};
        border-radius: {LAYOUT['border_radius_lg']}px;
    """


def badge_style(bg_color, text_color=None):
    """QSS for a small badge/chip."""
    tc = text_color or COLORS["t1"]
    return f"""
        background-color: {bg_color};
        color: {tc};
        border-radius: 10px;
        padding: 2px 10px;
        font-size: 11px;
        font-weight: 600;
    """


def accent_button_style(accent_color):
    """QSS for an accent-colored button."""
    return f"""
        QPushButton {{
            background-color: {accent_color};
            color: #FFFFFF;
            border: none;
            border-radius: {LAYOUT['border_radius']}px;
            padding: 8px 20px;
            font-size: 13px;
            font-weight: 600;
        }}
        QPushButton:hover {{
            background-color: {lighten(accent_color, 15)};
        }}
        QPushButton:pressed {{
            background-color: {darken(accent_color, 15)};
        }}
    """


def header_style():
    """QSS for the top header bar."""
    return f"""
        background-color: {COLORS['surf']};
        border-bottom: 1px solid {COLORS['b1']};
    """


def status_bar_style():
    """QSS for the bottom status bar."""
    return f"""
        background-color: {COLORS['surf']};
        border-top: 1px solid {COLORS['b1']};
    """


# ── QPainter Background Effects ────────────────────────────────────────────

class GlowBackground(QWidget):
    """Custom-painted background widget with glow blobs and dot grid.

    Paint order:
      1. Solid dark background fill
      2. Two radial-gradient glow blobs (purple top-left, cyan bottom-right)
      3. Subtle dot grid pattern (2x2px dots every 44px)

    Use as the scroll area's inner container instead of a plain QWidget.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # 1. Solid background
        painter.fillRect(self.rect(), QColor(COLORS["bg"]))

        # 2. Glow blobs
        # Top-left purple blob
        purple = QColor(COLORS["p1"])
        purple.setAlphaF(0.10)
        grad1 = QRadialGradient(QPointF(w * 0.15, h * 0.10), max(w, h) * 0.35)
        grad1.setColorAt(0.0, purple)
        grad1.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setBrush(grad1)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(w * 0.15, h * 0.10), w * 0.38, h * 0.45)

        # Bottom-right cyan blob
        cyan = QColor(COLORS["cy"])
        cyan.setAlphaF(0.06)
        grad2 = QRadialGradient(QPointF(w * 0.82, h * 0.75), max(w, h) * 0.30)
        grad2.setColorAt(0.0, cyan)
        grad2.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setBrush(grad2)
        painter.drawEllipse(QPointF(w * 0.82, h * 0.75), w * 0.30, h * 0.35)

        # 3. Dot grid pattern — 2x2px dots every 44px
        dot_color = QColor("#4A5280")
        dot_color.setAlphaF(0.08)
        painter.setBrush(dot_color)
        painter.setPen(Qt.PenStyle.NoPen)

        dot_size = 2
        spacing = 44
        # Only paint dots visible in the update region
        rect = event.rect()
        start_x = (rect.left() // spacing) * spacing
        start_y = (rect.top() // spacing) * spacing

        x = start_x
        while x < rect.right() + spacing:
            y = start_y
            while y < rect.bottom() + spacing:
                painter.drawRect(x, y, dot_size, dot_size)
                y += spacing
            x += spacing

        painter.end()


def apply_card_glow(widget, accent_hex, blur=20, alpha=0.15):
    """Apply a colored drop-shadow glow effect to a card widget.

    Args:
        widget: The QWidget to apply the effect to.
        accent_hex: Hex color string for the glow (e.g. '#8B5CF6').
        blur: Blur radius in pixels.
        alpha: Opacity of the glow (0.0–1.0).
    """
    shadow = QGraphicsDropShadowEffect(widget)
    glow_color = QColor(accent_hex)
    glow_color.setAlphaF(alpha)
    shadow.setColor(glow_color)
    shadow.setBlurRadius(blur)
    shadow.setOffset(0, 0)
    widget.setGraphicsEffect(shadow)
