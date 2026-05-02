"""RadioAI Studio Pro — Control Panel

Container widget with 4 tabs: Libraries, Scheduling, Settings, AI Magic.
Each tab is a separate widget page in a QStackedWidget.
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QStackedWidget, QLabel
from PyQt6.QtCore import Qt

from ui.theme import COLORS, font
from ui.control_panel.libraries_tab import LibrariesTab


class PlaceholderTab(QWidget):
    """Temporary placeholder for tabs not yet implemented."""

    def __init__(self, title, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label = QLabel(f"{title}\nComing in a future session")
        label.setFont(font("medium", 18))
        label.setStyleSheet(f"color: {COLORS['t3']};")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)


class ControlPanel(QWidget):
    """Main control panel with Libraries, Scheduling, Settings, AI Magic tabs."""

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.stack = QStackedWidget()

        # Tab 0: Libraries
        self.libraries_tab = LibrariesTab(self.db)
        self.stack.addWidget(self.libraries_tab)

        # Tab 1: Scheduling (placeholder)
        self.stack.addWidget(PlaceholderTab("Scheduling"))

        # Tab 2: Settings (placeholder)
        self.stack.addWidget(PlaceholderTab("Settings"))

        # Tab 3: AI Magic (placeholder)
        self.stack.addWidget(PlaceholderTab("AI Magic"))

        layout.addWidget(self.stack)

    def switch_tab(self, index):
        if 0 <= index < self.stack.count():
            self.stack.setCurrentIndex(index)
