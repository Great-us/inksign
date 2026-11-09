import os
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from pdf_annotator.main_window import MainWindow

APP_NAME = "墨签 InkSign"


def resource_path(relative: str) -> str:
    """Resolve a bundled asset both when run from source and when frozen
    into a PyInstaller --onefile exe (which extracts data files to _MEIPASS)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    icon_path = resource_path(os.path.join("assets", "app.ico"))
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    window = MainWindow()
    window.show()

    # Support: double-click a .pdf via "Open with", or drag a file onto the
    # app's exe/shortcut icon in Explorer — Windows passes the path as argv[1].
    if len(sys.argv) > 1:
        candidate = sys.argv[1]
        if os.path.isfile(candidate) and candidate.lower().endswith(".pdf"):
            window.load_pdf(candidate)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
