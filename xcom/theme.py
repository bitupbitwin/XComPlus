"""毛玻璃淡色主题：浅色渐变底 + 橙色光晕背景，半透明圆角玻璃面板，苹果系统橙点缀。"""

import tempfile
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import (QColor, QPainter, QPalette, QPen, QPixmap,
                           QPolygonF, QRadialGradient)
from PySide6.QtWidgets import QApplication, QWidget

ACCENT = "#FF9500"  # Apple 经典系统橙


def _arrow_urls():
    """生成 QSpinBox/QComboBox 用的上下箭头图片（QSS 自定义样式后 Qt 不再画默认箭头）。"""
    d = Path(tempfile.gettempdir())
    paths = {}
    for name, pts in (
        ("up", [(2.5, 7.5), (6.0, 4.0), (9.5, 7.5)]),
        ("down", [(2.5, 4.5), (6.0, 8.0), (9.5, 4.5)]),
    ):
        pm = QPixmap(12, 12)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor("#55555E"), 1.7, Qt.SolidLine,
                      Qt.RoundCap, Qt.RoundJoin))
        p.drawPolyline(QPolygonF([QPointF(x, y) for x, y in pts]))
        p.end()
        path = d / f"xcom_arrow_{name}.png"
        pm.save(str(path))
        paths[name] = path.as_posix()
    return paths["up"], paths["down"]


class Backdrop(QWidget):
    """主界面背景：浅色底上叠两团柔和光晕，透过半透明面板形成玻璃质感。"""

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor("#F4F3EF"))

        glow = QRadialGradient(w * 0.88, h * 0.08, max(w, h) * 0.65)
        glow.setColorAt(0.0, QColor(255, 149, 0, 52))
        glow.setColorAt(1.0, QColor(255, 149, 0, 0))
        p.fillRect(self.rect(), glow)

        cool = QRadialGradient(w * 0.06, h * 0.95, max(w, h) * 0.55)
        cool.setColorAt(0.0, QColor(120, 150, 220, 40))
        cool.setColorAt(1.0, QColor(120, 150, 220, 0))
        p.fillRect(self.rect(), cool)


def _palette() -> QPalette:
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor("#F4F3EF"))
    pal.setColor(QPalette.WindowText, QColor("#2B2B30"))
    pal.setColor(QPalette.Base, QColor("#FFFFFF"))
    pal.setColor(QPalette.Text, QColor("#2B2B30"))
    pal.setColor(QPalette.Button, QColor("#FFFFFF"))
    pal.setColor(QPalette.ButtonText, QColor("#2B2B30"))
    pal.setColor(QPalette.Highlight, QColor(ACCENT))
    pal.setColor(QPalette.HighlightedText, QColor("#1A1208"))
    pal.setColor(QPalette.ToolTipBase, QColor("#FFFFFF"))
    pal.setColor(QPalette.ToolTipText, QColor("#2B2B30"))
    pal.setColor(QPalette.PlaceholderText, QColor(0, 0, 0, 90))
    return pal


QSS = """
QMainWindow, QDialog, QMessageBox, QInputDialog { background: #F4F3EF; }
QLabel { color: #3C3C42; background: transparent; }
QLabel#editorTitle { color: #D97700; font-size: 14px; font-weight: 700; }

QGroupBox {
    background: rgba(255,255,255,150);
    border: 1px solid rgba(0,0,0,28);
    border-radius: 8px;
    margin-top: 14px;
    padding: 2px 1px 1px 1px;
    color: #3C3C42;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 5px; top: 0px;
    color: #D97700;
    font-weight: 600;
}

QPlainTextEdit {
    background: rgba(255,255,255,215);
    border: 1px solid rgba(0,0,0,32);
    border-radius: 7px;
    color: #26262B;
    selection-background-color: #FF9500;
    selection-color: #1A1208;
    padding: 4px;
    font-family: Consolas, Menlo, "Courier New", monospace;
}

QLineEdit, QComboBox, QSpinBox {
    background: rgba(255,255,255,205);
    border: 1px solid rgba(0,0,0,40);
    border-radius: 5px;
    padding: 2px 5px;
    color: #26262B;
    selection-background-color: #FF9500;
    selection-color: #1A1208;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border: 1px solid #FF9500; }

QSpinBox { padding-right: 18px; }
QSpinBox::up-button, QSpinBox::down-button {
    subcontrol-origin: border;
    width: 17px;
    background: rgba(0,0,0,12);
    border-left: 1px solid rgba(0,0,0,34);
}
QSpinBox::up-button {
    subcontrol-position: top right;
    border-top-right-radius: 4px;
    border-bottom: 1px solid rgba(0,0,0,20);
}
QSpinBox::down-button {
    subcontrol-position: bottom right;
    border-bottom-right-radius: 4px;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {
    background: rgba(255,149,0,110);
}
QSpinBox::up-button:pressed, QSpinBox::down-button:pressed {
    background: rgba(255,149,0,180);
}
QSpinBox::up-arrow { image: url("@UP@"); width: 10px; height: 10px; }
QSpinBox::down-arrow { image: url("@DOWN@"); width: 10px; height: 10px; }

QComboBox::drop-down { border: none; width: 18px; }
QComboBox::down-arrow { image: url("@DOWN@"); width: 10px; height: 10px; }
QComboBox QAbstractItemView {
    background: #FFFFFF;
    border: 1px solid rgba(0,0,0,45);
    border-radius: 5px;
    color: #26262B;
    selection-background-color: rgba(255,149,0,90);
    outline: none;
}

QPushButton {
    background: rgba(255,255,255,220);
    border: 1px solid rgba(0,0,0,45);
    border-radius: 5px;
    padding: 3px 7px;
    color: #2B2B30;
}
QPushButton:hover { background: rgba(255,236,210,235); }
QPushButton:pressed { background: rgba(0,0,0,22); }
QPushButton:disabled { color: rgba(0,0,0,80); background: rgba(0,0,0,10); }
QPushButton#primary {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #FFAA33, stop:1 #FF8A00);
    border: 1px solid rgba(220,140,20,180);
    color: #221302;
    font-weight: 700;
}
QPushButton#primary:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #FFB54D, stop:1 #FF9500);
}
QPushButton#primary:pressed { background: #E07F00; }

QCheckBox { color: #3C3C42; spacing: 4px; background: transparent; }
QCheckBox::indicator {
    width: 14px; height: 14px;
    border-radius: 3px;
    background: rgba(255,255,255,210);
    border: 1px solid rgba(0,0,0,70);
}
QCheckBox::indicator:hover { border: 1px solid rgba(230,140,30,200); }
QCheckBox::indicator:checked { background: #FF9500; border: 1px solid #E68600; }

QTabWidget::pane {
    background: rgba(255,255,255,130);
    border: 1px solid rgba(0,0,0,26);
    border-radius: 7px;
    top: -1px;
}
QTabBar::tab {
    background: transparent;
    color: #71717A;
    padding: 4px 9px;
    margin: 1px;
    border-radius: 5px;
}
QTabBar::tab:selected {
    background: rgba(255,149,0,52);
    color: #C46A00;
    font-weight: 600;
}
QTabBar::tab:hover:!selected { background: rgba(0,0,0,16); color: #2B2B30; }

QProgressBar {
    background: rgba(0,0,0,14);
    border: 1px solid rgba(0,0,0,32);
    border-radius: 5px;
    text-align: center;
    color: #2B2B30;
    font-size: 11px;
}
QProgressBar::chunk {
    border-radius: 4px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FFAA33, stop:1 #FF8A00);
}

QTableWidget {
    background: rgba(255,255,255,225);
    border: 1px solid rgba(0,0,0,28);
    border-radius: 6px;
    gridline-color: rgba(0,0,0,24);
    color: #26262B;
    selection-background-color: rgba(255,149,0,110);
    selection-color: #1A1208;
}
QTableWidget::item { padding: 1px 3px; }
QHeaderView::section {
    background: rgba(0,0,0,16);
    color: #4A4A52;
    border: none;
    border-right: 1px solid rgba(0,0,0,22);
    border-bottom: 1px solid rgba(0,0,0,22);
    padding: 3px;
}
QTableCornerButton::section { background: rgba(0,0,0,16); border: none; }

QStatusBar { background: transparent; color: #6E6E76; }
QStatusBar QLabel { color: #6E6E76; }
QStatusBar::item { border: none; }

QSplitter::handle:vertical {
    background: rgba(0,0,0,32);
    height: 5px;
    margin: 2px 10px;
    border-radius: 2px;
}
QSplitter::handle:vertical:hover { background: rgba(255,149,0,150); }

QMenu {
    background: #FFFFFF;
    border: 1px solid rgba(0,0,0,45);
    border-radius: 6px;
    padding: 2px;
    color: #26262B;
}
QMenu::item { padding: 4px 12px; border-radius: 4px; }
QMenu::item:selected { background: rgba(255,149,0,110); color: #1A1208; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical {
    background: rgba(0,0,0,60);
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: rgba(255,149,0,170); }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal {
    background: rgba(0,0,0,60);
    border-radius: 4px;
    min-width: 30px;
}
QScrollBar::handle:horizontal:hover { background: rgba(255,149,0,170); }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
"""


def apply_theme(window):
    app = QApplication.instance()
    app.setStyle("Fusion")
    app.setPalette(_palette())
    up, down = _arrow_urls()
    window.setStyleSheet(QSS.replace("@UP@", up).replace("@DOWN@", down))
