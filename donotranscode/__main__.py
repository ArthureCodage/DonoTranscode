import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from . import APP_NAME
from .main_window import MainWindow
from .theme import apply_dark_theme, make_icon


def main():
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Dono.DonoTranscode")
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("Dono")
    app.setWindowIcon(make_icon())
    apply_dark_theme(app)
    win = MainWindow()
    win.show()
    files = [Path(a) for a in sys.argv[1:] if Path(a).exists()]
    if files:
        win.tabs.currentWidget().add_paths(files)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
