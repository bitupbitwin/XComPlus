"""多条发送页签：12 条条目 + 循环发送。"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QGridLayout, QHBoxLayout, QVBoxLayout, QCheckBox,
    QLineEdit, QPushButton, QLabel, QSpinBox, QScrollArea,
)

ENTRY_COUNT = 12


class MultiSendPage(QWidget):
    """send_func(text: str, is_hex: bool) 由主窗口提供，负责实际发送。"""

    def __init__(self, send_func, parent=None):
        super().__init__(parent)
        self._send_func = send_func
        self._cycle_index = 0
        self._entries = []  # [(hex_chk, line_edit, btn), ...]

        grid = QGridLayout()
        grid.addWidget(QLabel("HEX"), 0, 0)
        grid.addWidget(QLabel("内容"), 0, 1)
        for i in range(ENTRY_COUNT):
            hex_chk = QCheckBox()
            edit = QLineEdit()
            btn = QPushButton(str(i + 1))
            btn.setFixedWidth(40)
            btn.clicked.connect(lambda _=False, idx=i: self._send_entry(idx))
            grid.addWidget(hex_chk, i + 1, 0, alignment=Qt.AlignCenter)
            grid.addWidget(edit, i + 1, 1)
            grid.addWidget(btn, i + 1, 2)
            self._entries.append((hex_chk, edit, btn))

        inner = QWidget()
        inner.setLayout(grid)
        scroll = QScrollArea()
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)

        self.cycle_chk = QCheckBox("循环发送")
        self.cycle_chk.toggled.connect(self._toggle_cycle)
        self.period_spin = QSpinBox()
        self.period_spin.setRange(1, 600000)
        self.period_spin.setValue(1000)
        self.period_spin.setSuffix(" ms")

        bottom = QHBoxLayout()
        bottom.addWidget(self.cycle_chk)
        bottom.addWidget(QLabel("周期:"))
        bottom.addWidget(self.period_spin)
        bottom.addStretch()

        layout = QVBoxLayout(self)
        layout.addWidget(scroll)
        layout.addLayout(bottom)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._cycle_tick)

    def _send_entry(self, idx) -> bool:
        hex_chk, edit, _ = self._entries[idx]
        text = edit.text()
        if not text:
            return False
        return self._send_func(text, hex_chk.isChecked())

    def _toggle_cycle(self, on: bool):
        if on:
            self._cycle_index = 0
            self._timer.start(self.period_spin.value())
        else:
            self._timer.stop()

    def _cycle_tick(self):
        self._timer.setInterval(self.period_spin.value())
        # 从当前位置往后找第一条非空条目发送
        for _ in range(ENTRY_COUNT):
            idx = self._cycle_index
            self._cycle_index = (self._cycle_index + 1) % ENTRY_COUNT
            if self._entries[idx][1].text():
                if not self._send_entry(idx):
                    self.cycle_chk.setChecked(False)
                return
        self.cycle_chk.setChecked(False)  # 全空则停止

    def stop_cycle(self):
        self.cycle_chk.setChecked(False)
