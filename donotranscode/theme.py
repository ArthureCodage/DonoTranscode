"""Thème sombre et icône de l'application."""
from __future__ import annotations

import sys

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QLinearGradient, QPainter, QPalette, QPixmap

ACCENT = "#3d8bff"

QSS = f"""
QToolTip {{ color: #e6e6e6; background: #2b2d31; border: 1px solid #44474d; padding: 4px; }}
QGroupBox {{ border: 1px solid #3a3d42; border-radius: 6px; margin-top: 14px; padding: 8px 6px 6px 6px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #9fc3ff; font-weight: bold; }}
QTabWidget::pane {{ border: 1px solid #3a3d42; border-radius: 4px; top: -1px; }}
QTabBar::tab {{ background: #26282c; padding: 7px 14px; border: 1px solid #3a3d42; border-bottom: none;
               border-top-left-radius: 5px; border-top-right-radius: 5px; margin-right: 2px; color: #b8bcc4; }}
QTabBar::tab:selected {{ background: #33363b; color: #ffffff; border-bottom: 2px solid {ACCENT}; }}
QTabBar::tab:hover {{ color: #ffffff; }}
QPushButton {{ background: #33363b; border: 1px solid #4a4e55; border-radius: 4px; padding: 5px 12px; }}
QPushButton:hover {{ background: #3d4147; border-color: #5a5f67; }}
QPushButton:pressed {{ background: #2a2c30; }}
QPushButton:disabled {{ color: #6b6f76; border-color: #3a3d42; }}
QPushButton#primary {{ background: {ACCENT}; border: 1px solid {ACCENT}; color: white; font-weight: bold; padding: 7px 18px; }}
QPushButton#primary:hover {{ background: #5a9dff; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit {{
    background: #1b1c1f; border: 1px solid #44474d; border-radius: 4px; padding: 3px 5px; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QListWidget, QTableWidget {{ background: #1b1c1f; border: 1px solid #3a3d42; border-radius: 4px; }}
QHeaderView::section {{ background: #2b2d31; border: none; border-right: 1px solid #3a3d42; padding: 4px 6px; }}
QProgressBar {{ border: 1px solid #44474d; border-radius: 3px; background: #1b1c1f; text-align: center; height: 16px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 2px; }}
QSplitter::handle {{ background: #2b2d31; }}
QScrollArea {{ background: transparent; }}
QLabel#hint {{ color: #8b9099; }}
QLabel#warn {{ color: #ffb648; }}
"""


def apply_dark_theme(app):
    app.setStyle("Fusion")
    p = QPalette()
    window, base, alt = QColor(30, 31, 34), QColor(27, 28, 31), QColor(38, 40, 44)
    text, dim = QColor(226, 228, 232), QColor(120, 124, 132)
    accent = QColor(ACCENT)
    p.setColor(QPalette.Window, window)
    p.setColor(QPalette.WindowText, text)
    p.setColor(QPalette.Base, base)
    p.setColor(QPalette.AlternateBase, alt)
    p.setColor(QPalette.ToolTipBase, alt)
    p.setColor(QPalette.ToolTipText, text)
    p.setColor(QPalette.Text, text)
    p.setColor(QPalette.Button, QColor(51, 54, 59))
    p.setColor(QPalette.ButtonText, text)
    p.setColor(QPalette.BrightText, QColor(255, 80, 80))
    p.setColor(QPalette.Highlight, accent)
    p.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    p.setColor(QPalette.Link, accent)
    p.setColor(QPalette.PlaceholderText, dim)
    for role in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, dim)
    app.setPalette(p)
    app.setStyleSheet(QSS)


def make_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        qp = QPainter(pm)
        qp.setRenderHint(QPainter.Antialiasing)
        grad = QLinearGradient(0, 0, size, size)
        grad.setColorAt(0, QColor("#3d8bff"))
        grad.setColorAt(1, QColor("#7b4dff"))
        qp.setBrush(QBrush(grad))
        qp.setPen(Qt.NoPen)
        r = size * 0.22
        qp.drawRoundedRect(QRectF(0, 0, size, size), r, r)
        qp.setPen(QColor("white"))
        f = QFont("Segoe UI", max(int(size * 0.36), 5))
        f.setBold(True)
        qp.setFont(f)
        qp.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, "DT")
        qp.end()
        icon.addPixmap(pm)
    return icon


def dark_title_bar(widget):
    """Barre de titre sombre sous Windows 10/11."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = int(widget.winId())
        value = ctypes.c_int(1)
        for attr in (20, 19):
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value),
                                                          ctypes.sizeof(value)) == 0:
                break
    except Exception:
        pass
