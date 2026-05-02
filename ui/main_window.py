"""RadioAI Studio Pro — Main Window (Hybrid Architecture)

Renders the entire UI in a QWebEngineView loading control_panel.html.
Python backend communicates with JS via QWebChannel bridge.

Navigation model:
- Tab switching (Libraries/Scheduling/Settings/AI Magic) is pure JS/CSS
  inside control_panel.html — Python is NOT involved.
- Sub-screen navigation (Songs Library, Clock Editor, etc.) loads
  separate HTML files via Python bridge.
- Back-navigation from sub-screens uses window.location.href with
  hash fragments (#scheduling, #libraries) — no Python roundtrip.
"""

import os

from PyQt6.QtWidgets import QMainWindow
from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebChannel import QWebChannel

from ui.bridge import Bridge
from core.database import DatabaseManager


class StudioWindow(QMainWindow):
    """Persistent Studio window — created once, hidden (not destroyed) when
    the user leaves it. This keeps VLC decks, timers and JS state alive so
    playback is NEVER interrupted by tab/page switching.
    """

    def __init__(self, bridge, web_dir):
        super().__init__()
        self.setWindowTitle("RadioAI Studio — On Air")
        self.setMinimumSize(1280, 720)
        self.resize(1600, 980)

        self.channel = QWebChannel(self)
        self.channel.registerObject("bridge", bridge)

        self.web_view = QWebEngineView(self)
        self.web_view.page().setWebChannel(self.channel)
        self.web_view.page().setBackgroundColor(QColor("#070812"))

        html_path = os.path.join(web_dir, "studio_screen.html")
        self.web_view.setUrl(QUrl.fromLocalFile(html_path))

        self.setCentralWidget(self.web_view)

    def closeEvent(self, event):
        """Hide instead of destroy — keeps playback alive when user closes."""
        event.ignore()
        self.hide()


class MainWindow(QMainWindow):
    """Root application window — hosts a QWebEngineView with the Control Panel
    and Library screens. Studio runs in its own persistent window (StudioWindow)
    so playback is unaffected by navigation here.
    """

    def __init__(self):
        super().__init__()
        self.db = DatabaseManager()
        self.setWindowTitle("RadioAI Studio Pro")
        self.setMinimumSize(1280, 720)
        self.resize(1440, 900)
        self._studio_window = None
        self._build_ui()
        self.showMaximized()

    def _build_ui(self):
        self.bridge = Bridge(self)
        self.bridge.library_requested.connect(self._on_library_requested)
        self.bridge.studio_requested.connect(self._on_studio_requested)
        self.bridge.navigate_requested.connect(self._on_navigate)
        self.bridge.studio_close_requested.connect(self._on_studio_close)

        self.channel = QWebChannel(self)
        self.channel.registerObject("bridge", self.bridge)

        self.web_view = QWebEngineView(self)
        self.web_view.page().setWebChannel(self.channel)
        self.web_view.page().setBackgroundColor(QColor("#070812"))

        self._web_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")

        html_path = os.path.join(self._web_dir, "control_panel.html")
        self.web_view.setUrl(QUrl.fromLocalFile(html_path))

        self.setCentralWidget(self.web_view)

    def _navigate_to(self, page_name):
        """Load a sub-screen HTML file in the main window."""
        html_path = os.path.join(self._web_dir, f"{page_name}.html")
        if os.path.exists(html_path):
            self.web_view.setUrl(QUrl.fromLocalFile(html_path))

    def _on_library_requested(self, key):
        page_map = {
            "songs": "songs_library",
            "spots": "spots_library",
            "jingles": "jingles_library",
            "instant": "instant_jingles",
            "sweepers": "sweepers_library",
            "stitcher": "stitcher",
        }
        self._navigate_to(page_map.get(key, "control_panel"))

    def _on_studio_requested(self):
        """Show the Studio window. Create it on first call, raise on subsequent
        calls. Never reload — playback stays alive across show/hide cycles."""
        if self._studio_window is None:
            self._studio_window = StudioWindow(self.bridge, self._web_dir)
            self._studio_window.showMaximized()
        else:
            if self._studio_window.isMinimized():
                self._studio_window.showNormal()
            self._studio_window.show()
            self._studio_window.raise_()
            self._studio_window.activateWindow()

    def _on_studio_close(self):
        """Called when Studio JS requests 'go back' — just hide the window."""
        if self._studio_window is not None:
            self._studio_window.hide()
        self.raise_()
        self.activateWindow()

    def _on_navigate(self, page):
        """Handle navigation requests from JS (sub-screen file navigation).

        Special case: any request to navigate to 'studio_screen' is
        intercepted and routed to the persistent Studio window instead.
        This guarantees that ALL "Open Studio" buttons across every HTML
        screen (which historically call navigateTo('studio_screen')) now
        raise the existing Studio window without reloading it — playback
        is never interrupted.
        """
        if page == "studio_screen":
            self._on_studio_requested()
            return
        self._navigate_to(page)

    def closeEvent(self, event):
        """Ensure the Studio window is fully closed when the app quits."""
        if self._studio_window is not None:
            self._studio_window.deleteLater()
            self._studio_window = None
        super().closeEvent(event)
