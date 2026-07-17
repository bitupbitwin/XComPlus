"""主窗口：日志接收区 + 单条/多条发送页签 + 状态栏。"""

from __future__ import annotations

import codecs
import json
import os
from datetime import datetime

import serial
from PySide6.QtCore import QPoint, QSize, Qt, QTimer
from PySide6.QtGui import (
    QColor, QFont, QIcon, QPainter, QPen, QPixmap, QPolygon, QTextCursor,
)
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QTabWidget, QHBoxLayout, QVBoxLayout, QGridLayout,
    QGroupBox, QLabel, QComboBox, QPushButton, QCheckBox, QSpinBox,
    QPlainTextEdit, QMessageBox, QFileDialog, QSplitter, QApplication,
    QLineEdit, QProgressBar, QLayout, QSizePolicy,
)

from . import __version__
from .icon import app_icon
from .paths import app_dir
from .serial_manager import SerialManager, list_ports
from .multi_send import MultiSendPage
from .theme import Backdrop, apply_theme

BAUDRATES = [
    "custom", "110", "300", "600", "1200", "2400", "4800", "9600",
    "14400", "19200", "38400", "43000", "57600", "76800", "115200",
    "128000", "230400", "256000", "460800", "921600", "1000000",
    "2000000", "3000000",
]
RX_BUFFER_LIMIT = 1024 * 1024       # 接收缓冲上限 1MB
DISPLAY_CHAR_LIMIT = 8 * 1024 * 1024  # 显示文本超过该字符数时按缓冲重渲染
FILE_SEND_CHUNK = 64 * 1024
# 右侧设置栏的常态宽度；需要微调左右占比时只改这里即可。
RIGHT_PANEL_WIDTH = 155
DEFAULT_QUICK_COMMAND = "switch_list(0x1f)"
SINGLE_SEND_CONFIG_PATH = app_dir() / "xcom_single_send.json"


class PortComboBox(QComboBox):
    """串口选择下拉框：每次弹出前自动枚举端口。"""

    def __init__(self, refresh_cb, parent=None):
        super().__init__(parent)
        self._refresh_cb = refresh_cb

    def showPopup(self):
        self._refresh_cb()
        super().showPopup()


def parse_hex(text: str) -> bytes:
    """解析 "AA BB 0F" 形式的 16 进制字符串，非法时抛 ValueError。"""
    s = "".join(text.split())
    if len(s) % 2 != 0:
        raise ValueError("16进制数据长度必须为偶数个字符")
    try:
        return bytes.fromhex(s)
    except ValueError:
        raise ValueError("包含非16进制字符") from None


def port_action_icon(port_is_open: bool) -> QIcon:
    """生成串口操作图标：打开后显示醒目的红色停止图标。"""
    pixmap = QPixmap(20, 20)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    if port_is_open:
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#FF453A"))
        painter.drawEllipse(1, 1, 18, 18)
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawRoundedRect(6, 6, 8, 8, 1.5, 1.5)
    else:
        # 主按钮是橙色底，使用深色图形以保证缩小后仍有清晰对比。
        painter.setPen(QPen(QColor("#221302"), 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(1.5, 1.5, 17, 17)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#221302"))
        painter.drawPolygon(QPolygon([QPoint(7, 5), QPoint(15, 10),
                                      QPoint(7, 15)]))
    painter.end()
    return QIcon(pixmap)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("X-COM+ 串口调试助手")
        self.setWindowIcon(app_icon())  # 弹窗继承主窗口图标
        self.resize(960, 640)

        self.sm = SerialManager()
        self.rx_chunks = []      # [(datetime, bytes), ...]
        self.rx_buffer_size = 0
        self.rx_count = 0
        self.tx_count = 0
        self.display_paused = False
        self._sending_file = False
        self._file_stop = False
        self._tick_busy = False
        self._single_save_error_shown = False
        self._single_save_timer = QTimer(self)
        self._single_save_timer.setSingleShot(True)
        self._single_save_timer.setInterval(300)
        self._single_save_timer.timeout.connect(self._save_single_send)

        self._build_ui()
        # 必须在状态栏和中央布局创建后设置，避免它们重新推高窗口最小尺寸。
        # 内容按现有布局直接裁切，可压缩到只剩标题栏或很窄的一条。
        self.setMinimumSize(120, 0)
        apply_theme(self)
        self._reset_decoder()
        self.refresh_ports()
        self._update_status()

    # ---------- UI 构建 ----------

    def _build_ui(self):
        self.multi_page = MultiSendPage(self.send_data)
        self.setCentralWidget(self._build_main_page())

        self.version_label = QLabel(f"X-COM+ v{__version__}")
        self.version_label.setToolTip(
            f"单条配置：{SINGLE_SEND_CONFIG_PATH}")
        self.count_label = QLabel()
        self.clock_label = QLabel()
        reset_btn = QPushButton("复位计数")
        reset_btn.clicked.connect(self.reset_counts)
        sb = self.statusBar()
        sb.addWidget(self.version_label, 1)
        sb.addPermanentWidget(self.count_label)
        sb.addPermanentWidget(self.clock_label)
        sb.addPermanentWidget(reset_btn)

        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start(1000)
        self._update_clock()

    def _build_main_page(self) -> QWidget:
        # 接收区
        self.recv_text = QPlainTextEdit()
        self.recv_text.setReadOnly(True)
        self.recv_text.setMaximumBlockCount(50000)  # 限制显示行数防内存膨胀
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.Monospace)
        self.recv_text.setFont(mono)

        # 右侧串口设置：串口选择下拉时自动枚举端口，无需刷新按钮
        self.port_combo = PortComboBox(self.refresh_ports)
        # 串口描述可能很长，不能让内容长度反向撑宽整个右侧设置栏。
        self.port_combo.setSizeAdjustPolicy(
            QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.port_combo.setMinimumContentsLength(10)
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(BAUDRATES)
        self.baud_combo.setEditable(True)
        self.baud_combo.setCurrentIndex(self.baud_combo.findText("115200"))
        self.baud_combo.activated.connect(self._baud_selected)
        self.stop_combo = QComboBox()
        self.stop_combo.addItems(["1", "1.5", "2"])
        self.data_combo = QComboBox()
        self.data_combo.addItems(["8", "7", "6", "5"])
        self.parity_combo = QComboBox()
        self.parity_combo.addItems(["无", "奇", "偶", "Mark", "Space"])
        self.flow_combo = QComboBox()
        self.flow_combo.addItems(["无", "RTS/CTS", "XON/XOFF"])
        self.encoding_combo = QComboBox()
        self.encoding_combo.addItems(["UTF-8", "GBK"])
        self.encoding_combo.currentIndexChanged.connect(self.rerender_recv)
        self.open_btn = QPushButton("打开串口")
        self.open_btn.setObjectName("primary")
        self.open_btn.setIconSize(QSize(16, 16))
        self.open_btn.clicked.connect(self.toggle_port)
        self._sync_port_button()

        grid = QGridLayout()
        grid.setContentsMargins(5, 8, 5, 6)
        grid.setHorizontalSpacing(3)
        grid.setVerticalSpacing(5)
        rows = [
            ("串口选择", self.port_combo),
            ("波特率", self.baud_combo),
            ("停止位", self.stop_combo),
            ("数据位", self.data_combo),
            ("校验位", self.parity_combo),
            ("流控", self.flow_combo),
            ("编码", self.encoding_combo),
        ]
        grid.setColumnStretch(1, 1)
        for r, (name, w) in enumerate(rows):
            grid.addWidget(QLabel(name), r, 0)
            grid.addWidget(w, r, 1)
        grid.addWidget(QLabel("串口操作"), len(rows), 0)
        grid.addWidget(self.open_btn, len(rows), 1)  # 与上方下拉框同宽对齐

        self.dtr_chk = QCheckBox("DTR")
        self.dtr_chk.toggled.connect(lambda on: self.sm.set_dtr(on))
        self.rts_chk = QCheckBox("RTS")
        self.rts_chk.toggled.connect(lambda on: self.sm.set_rts(on))
        dtr_rts = QHBoxLayout()
        dtr_rts.addWidget(self.dtr_chk)
        dtr_rts.addWidget(self.rts_chk)
        grid.addLayout(dtr_rts, len(rows) + 1, 0, 1, 2)

        settings_box = QGroupBox("串口设置")
        settings_box.setLayout(grid)

        # 接收控制
        self.hex_recv_chk = QCheckBox("16进制显示")
        self.hex_recv_chk.toggled.connect(self.rerender_recv)
        self.timestamp_chk = QCheckBox("显示时间戳")
        self.timestamp_chk.toggled.connect(self.rerender_recv)
        self.pause_chk = QCheckBox("停止显示")
        self.pause_chk.toggled.connect(self._toggle_pause)
        save_btn = QPushButton("保存窗口")
        save_btn.clicked.connect(self.save_window)
        clear_recv_btn = QPushButton("清除接收")
        clear_recv_btn.clicked.connect(self.clear_recv)

        recv_ctrl = QVBoxLayout()
        recv_ctrl.setContentsMargins(5, 8, 5, 6)
        recv_ctrl.setSpacing(4)
        for w in (self.hex_recv_chk, self.timestamp_chk, self.pause_chk):
            recv_ctrl.addWidget(w)
        recv_btn_row = QHBoxLayout()
        recv_btn_row.addWidget(save_btn)
        recv_btn_row.addWidget(clear_recv_btn)
        recv_ctrl.addLayout(recv_btn_row)
        recv_box = QGroupBox("接收设置")
        recv_box.setLayout(recv_ctrl)

        # 高频发送：右侧常驻一个最常用命令，点击即可按文本 + CRLF 发送。
        self.quick_send_edit = QLineEdit(DEFAULT_QUICK_COMMAND)
        self.quick_send_edit.setPlaceholderText("输入常用命令")
        quick_send_btn = QPushButton("发送")
        quick_send_btn.setObjectName("primary")
        quick_send_btn.setFixedWidth(70)
        quick_send_btn.clicked.connect(self.send_quick_command)
        quick_layout = QVBoxLayout()
        quick_layout.setContentsMargins(5, 8, 5, 6)
        quick_layout.setSpacing(4)
        quick_layout.addWidget(self.quick_send_edit)
        quick_layout.addWidget(quick_send_btn, alignment=Qt.AlignHCenter)
        quick_box = QGroupBox("高频发送")
        quick_box.setLayout(quick_layout)

        right = QVBoxLayout()
        right.setContentsMargins(3, 4, 3, 4)
        right.setSpacing(6)
        right.addWidget(settings_box)
        right.addWidget(recv_box)
        right.addWidget(self.multi_page.controls_box)
        right.addWidget(quick_box)
        right.addStretch()
        for box in (settings_box, recv_box, self.multi_page.controls_box,
                    quick_box):
            box.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        right_panel = QWidget()
        right_panel.setLayout(right)
        right_panel.setFixedWidth(RIGHT_PANEL_WIDTH)

        # 发送区：压缩高度，让接收日志区占比更大
        self.send_text = QPlainTextEdit()
        self.send_text.setFixedHeight(55)
        self.hex_send_chk = QCheckBox("16进制发送")
        self.newline_chk = QCheckBox("发送新行")
        self.timer_send_chk = QCheckBox("定时发送")
        self.timer_send_chk.toggled.connect(self._toggle_timer_send)
        self.period_spin = QSpinBox()
        self.period_spin.setRange(1, 600000)
        self.period_spin.setValue(1000)
        self.period_spin.setSuffix(" ms")
        send_btn = QPushButton("发送")
        send_btn.setObjectName("primary")
        send_btn.setFixedSize(64, 55)
        send_btn.clicked.connect(self.send_current)
        clear_send_btn = QPushButton("清除发送")
        clear_send_btn.clicked.connect(self.send_text.clear)

        # 文件发送行（仿 XCOM：路径框 + 打开文件/发送文件/停止发送）
        self.file_edit = QLineEdit()
        self.file_edit.setPlaceholderText("要发送的文件")
        open_file_btn = QPushButton("打开文件")
        open_file_btn.clicked.connect(self.open_file)
        send_file_btn = QPushButton("发送文件")
        send_file_btn.clicked.connect(self.send_file)
        stop_send_btn = QPushButton("停止发送")
        stop_send_btn.clicked.connect(self.stop_send)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFixedHeight(16)

        input_row = QHBoxLayout()
        input_row.addWidget(self.send_text, 1)
        input_row.addWidget(send_btn)

        file_row = QHBoxLayout()
        file_row.addWidget(self.timer_send_chk)
        file_row.addWidget(self.period_spin)
        file_row.addWidget(self.file_edit, 1)
        file_row.addWidget(open_file_btn)
        file_row.addWidget(send_file_btn)
        file_row.addWidget(stop_send_btn)

        opt_row = QHBoxLayout()
        opt_row.addWidget(self.hex_send_chk)
        opt_row.addWidget(self.newline_chk)
        opt_row.addWidget(self.progress, 1)
        opt_row.addWidget(clear_send_btn)

        send_layout = QVBoxLayout()
        send_layout.setContentsMargins(6, 4, 6, 4)
        send_layout.setSpacing(3)
        send_layout.addLayout(input_row)
        send_layout.addLayout(file_row)
        send_layout.addLayout(opt_row)
        send_layout.addStretch()
        send_widget = QWidget()
        send_widget.setLayout(send_layout)

        # 下方页签切换单条/多条发送，接收日志区始终在上方；分割条可拖动调比例
        self.send_tabs = QTabWidget()
        self.send_tabs.addTab(send_widget, "单条发送")
        self.send_tabs.addTab(self.multi_page, "多条发送")

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.recv_text)
        splitter.addWidget(self.send_tabs)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setCollapsible(0, False)
        splitter.setSizes([440, 195])

        layout = QHBoxLayout()
        layout.setSizeConstraint(QLayout.SetNoConstraint)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        layout.addWidget(splitter, 1)
        layout.addWidget(right_panel)
        page = Backdrop()
        page.setMinimumSize(0, 0)
        page.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        page.setLayout(layout)

        self.send_timer = QTimer(self)
        self.send_timer.timeout.connect(self._timer_send_tick)
        self._load_single_send()
        self.send_text.textChanged.connect(self._schedule_single_send_save)
        self.hex_send_chk.toggled.connect(self._schedule_single_send_save)
        self.newline_chk.toggled.connect(self._schedule_single_send_save)
        self.period_spin.valueChanged.connect(self._schedule_single_send_save)
        self.file_edit.textChanged.connect(self._schedule_single_send_save)
        self.baud_combo.currentTextChanged.connect(
            self._schedule_single_send_save)
        self.quick_send_edit.textChanged.connect(
            self._schedule_single_send_save)
        # 首次启动也立即创建配置文件，便于用户确认实际运行版本和保存位置。
        if not SINGLE_SEND_CONFIG_PATH.exists():
            self._save_single_send()
        return page

    # ---------- 单条发送持久化 ----------

    def _schedule_single_send_save(self, *_):
        """输入停止 300ms 后落盘，兼顾实时保存与减少磁盘写入。"""
        self._single_save_timer.start()

    def _load_single_send(self):
        try:
            data = json.loads(SINGLE_SEND_CONFIG_PATH.read_text(
                encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return
        if not isinstance(data, dict):
            return
        baudrate = str(data.get("baudrate", "")).strip()
        if baudrate:
            index = self.baud_combo.findText(baudrate)
            if index >= 0:
                self.baud_combo.setCurrentIndex(index)
            else:
                self.baud_combo.setCurrentIndex(-1)
                self.baud_combo.setEditText(baudrate)
        self.send_text.setPlainText(str(data.get("text", "")))
        self.hex_send_chk.setChecked(bool(data.get("hex", False)))
        self.newline_chk.setChecked(bool(data.get("newline", False)))
        try:
            period = int(data.get("period_ms", 1000))
        except (TypeError, ValueError):
            period = 1000
        self.period_spin.setValue(max(1, min(600000, period)))
        self.file_edit.setText(str(data.get("file_path", "")))
        self.quick_send_edit.setText(str(
            data.get("quick_command", DEFAULT_QUICK_COMMAND)))

    def _save_single_send(self):
        data = {
            "baudrate": self.baud_combo.currentText().strip(),
            "text": self.send_text.toPlainText(),
            "hex": self.hex_send_chk.isChecked(),
            "newline": self.newline_chk.isChecked(),
            "period_ms": self.period_spin.value(),
            "file_path": self.file_edit.text(),
            "quick_command": self.quick_send_edit.text(),
        }
        temp_path = SINGLE_SEND_CONFIG_PATH.with_suffix(".json.tmp")
        try:
            SINGLE_SEND_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            temp_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8")
            temp_path.replace(SINGLE_SEND_CONFIG_PATH)
            self._single_save_error_shown = False
        except OSError as e:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            if not self._single_save_error_shown:
                self._single_save_error_shown = True
                QMessageBox.warning(
                    self, "单条发送配置保存失败",
                    f"无法保存到：\n{SINGLE_SEND_CONFIG_PATH}\n\n{e}")

    # ---------- 串口开关 ----------

    def _baud_selected(self, index: int):
        """选择 custom 后清空编辑框，直接等待用户输入自定义波特率。"""
        if self.baud_combo.itemText(index) == "custom":
            editor = self.baud_combo.lineEdit()
            editor.clear()
            editor.setPlaceholderText("输入自定义波特率")

    def _sync_port_button(self):
        """让按钮的文字、图标和提示始终反映当前串口状态。"""
        if self.sm.is_open:
            self.open_btn.setText("关闭串口")
            self.open_btn.setIcon(port_action_icon(True))
            self.open_btn.setToolTip("串口已打开，点击关闭")
        else:
            self.open_btn.setText("打开串口")
            self.open_btn.setIcon(port_action_icon(False))
            self.open_btn.setToolTip("串口已关闭，点击打开")

    def refresh_ports(self):
        current = self.port_combo.currentData()
        self.port_combo.clear()
        for device, desc in list_ports():
            self.port_combo.addItem(f"{device}  {desc}", device)
        if current is not None:
            idx = self.port_combo.findData(current)
            if idx >= 0:
                self.port_combo.setCurrentIndex(idx)

    def toggle_port(self):
        if self.sm.is_open:
            self.close_port()
            return
        port = self.port_combo.currentData()
        if not port:
            QMessageBox.warning(self, "提示", "没有可用串口")
            return
        try:
            baud = int(self.baud_combo.currentText())
        except ValueError:
            QMessageBox.warning(self, "提示", "波特率必须是整数")
            return
        try:
            self.sm.open(
                port=port,
                baudrate=baud,
                bytesize=int(self.data_combo.currentText()),
                stopbits=self.stop_combo.currentText(),
                parity=self.parity_combo.currentText(),
                flow=self.flow_combo.currentText(),
                on_data=self.on_data_received,
                on_error=self.on_serial_error,
            )
        except Exception as e:
            QMessageBox.critical(self, "打开串口失败", str(e))
            return
        self.sm.set_dtr(self.dtr_chk.isChecked())
        self.sm.set_rts(self.rts_chk.isChecked())
        self._sync_port_button()
        self._set_settings_enabled(False)
        self._update_status()

    def close_port(self):
        self.send_timer.stop()
        self.timer_send_chk.setChecked(False)
        self.multi_page.stop_cycle()
        self.sm.close()
        self._sync_port_button()
        self._set_settings_enabled(True)
        self._update_status()

    def _set_settings_enabled(self, on: bool):
        for w in (self.port_combo, self.baud_combo, self.stop_combo,
                  self.data_combo, self.parity_combo, self.flow_combo):
            w.setEnabled(on)

    def on_serial_error(self, msg: str):
        self.close_port()
        QMessageBox.critical(self, "串口异常", msg)

    # ---------- 接收 ----------

    def on_data_received(self, data: bytes):
        self.rx_count += len(data)
        now = datetime.now()
        self.rx_chunks.append((now, data))
        self.rx_buffer_size += len(data)
        while self.rx_buffer_size > RX_BUFFER_LIMIT and self.rx_chunks:
            _, old = self.rx_chunks.pop(0)
            self.rx_buffer_size -= len(old)
        if not self.display_paused:
            self._append_text(self._format_chunk(now, data))
            # 无换行数据（如 HEX 显示）不受行数限制约束，超限后整体重渲染
            if self.recv_text.document().characterCount() > DISPLAY_CHAR_LIMIT:
                self.rerender_recv()
        self._update_status()

    def _reset_decoder(self):
        # 增量解码：UTF-8/GBK 多字节字符被分包接收时不会显示成乱码
        self._decoder = codecs.getincrementaldecoder(
            self.encoding_combo.currentText())(errors="replace")

    def _format_chunk(self, ts: datetime, data: bytes) -> str:
        if self.hex_recv_chk.isChecked():
            body = " ".join(f"{b:02X}" for b in data) + " "
        else:
            body = self._decoder.decode(data)
        if self.timestamp_chk.isChecked():
            return f"\n[{ts.strftime('%H:%M:%S.%f')[:-3]}] {body}"
        return body

    def _append_text(self, text: str):
        # 不动用户光标/选区：在文档末尾插入；仅当原本就在底部时才自动跟随滚动
        sb = self.recv_text.verticalScrollBar()
        at_bottom = sb.value() >= sb.maximum() - 4
        cursor = QTextCursor(self.recv_text.document())
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(text)
        if at_bottom:
            sb.setValue(sb.maximum())

    def _scroll_recv_to_bottom(self):
        """发送指令后定位到最新日志，让随后返回的数据持续自动跟随。"""
        sb = self.recv_text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def rerender_recv(self):
        self._reset_decoder()
        self.recv_text.setPlainText(
            "".join(self._format_chunk(ts, d) for ts, d in self.rx_chunks))
        self.recv_text.moveCursor(QTextCursor.End)

    def _toggle_pause(self, on: bool):
        self.display_paused = on
        if not on:
            self.rerender_recv()

    def clear_recv(self):
        self.rx_chunks.clear()
        self.rx_buffer_size = 0
        self._reset_decoder()
        self.recv_text.clear()

    def save_window(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "保存窗口", "xcom_recv.txt", "文本文件 (*.txt);;所有文件 (*)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.recv_text.toPlainText())
        except OSError as e:
            QMessageBox.critical(self, "保存失败", str(e))

    # ---------- 发送 ----------

    def send_quick_command(self) -> bool:
        text = self.quick_send_edit.text().strip()
        if not text:
            QMessageBox.warning(self, "提示", "高频发送命令不能为空")
            return False
        return self.send_data(text, is_hex=False, newline=True)

    def send_data(self, text: str, is_hex: bool, newline: bool = False) -> bool:
        """所有发送的统一出口，返回是否发送成功。"""
        if not self.sm.is_open:
            QMessageBox.warning(self, "提示", "串口未打开")
            return False
        if self._sending_file:
            QMessageBox.warning(self, "提示", "正在发送文件，请稍候")
            return False
        try:
            if is_hex:
                data = parse_hex(text)
            else:
                data = text.encode(self.encoding_combo.currentText(),
                                   errors="replace")
            if newline:
                data += b"\r\n"
            self.sm.write(data)
            # 用户主动发送指令时，历史日志阅读状态结束，切回最新日志。
            # 单条和多条发送都经过此统一出口，因此两处行为保持一致。
            self._scroll_recv_to_bottom()
        except ValueError as e:
            QMessageBox.warning(self, "16进制格式错误", str(e))
            return False
        except serial.SerialTimeoutException:
            QMessageBox.warning(self, "发送超时",
                                "串口写入超时，可能被流控(CTS)阻塞")
            return False
        except Exception as e:
            self.on_serial_error(str(e))
            return False
        self.tx_count += len(data)
        self._update_status()
        return True

    def send_current(self) -> bool:
        return self.send_data(self.send_text.toPlainText(),
                              self.hex_send_chk.isChecked(),
                              self.newline_chk.isChecked())

    def _toggle_timer_send(self, on: bool):
        if on:
            if not self.sm.is_open:
                QMessageBox.warning(self, "提示", "串口未打开")
                self.timer_send_chk.setChecked(False)
                return
            self.send_timer.start(self.period_spin.value())
        else:
            self.send_timer.stop()

    def _timer_send_tick(self):
        # 重入保护：发送失败弹出的模态对话框会继续跑事件循环，
        # 期间定时器再触发会导致对话框无限叠加
        if self._tick_busy:
            return
        self._tick_busy = True
        try:
            self.send_timer.setInterval(self.period_spin.value())
            if not self.send_current():
                self.timer_send_chk.setChecked(False)
        finally:
            self._tick_busy = False

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "打开文件")
        if path:
            self.file_edit.setText(path)

    def stop_send(self):
        self._file_stop = True
        self.timer_send_chk.setChecked(False)

    def send_file(self):
        if not self.sm.is_open:
            QMessageBox.warning(self, "提示", "串口未打开")
            return
        if self._sending_file:
            QMessageBox.warning(self, "提示", "正在发送文件")
            return
        path = self.file_edit.text().strip()
        if not path:
            self.open_file()
            path = self.file_edit.text().strip()
            if not path:
                return
        try:
            total = os.path.getsize(path)
        except OSError as e:
            QMessageBox.critical(self, "发送文件失败", str(e))
            return
        # 流式分块发送并处理事件：大文件不占内存不卡界面；
        # 停止发送/关串口可中止，进度条实时刷新
        self._sending_file = True
        self._file_stop = False
        self.progress.setValue(0)
        sent = 0
        try:
            with open(path, "rb") as f:
                while self.sm.is_open and not self._file_stop:
                    chunk = f.read(FILE_SEND_CHUNK)
                    if not chunk:
                        break
                    self.sm.write(chunk)
                    sent += len(chunk)
                    self.tx_count += len(chunk)
                    if total:
                        self.progress.setValue(int(sent * 100 / total))
                    QApplication.processEvents()
            if sent >= total and not self._file_stop:
                self.progress.setValue(100)  # 完整发完（含空文件）进度置满
        except serial.SerialTimeoutException:
            QMessageBox.warning(self, "发送超时",
                                "串口写入超时，文件发送已中止")
        except serial.SerialException as e:
            self.on_serial_error(str(e))
        except OSError as e:
            QMessageBox.critical(self, "发送文件失败", str(e))
        finally:
            self._sending_file = False
        self._update_status()

    # ---------- 状态栏 ----------

    def _update_clock(self):
        self.clock_label.setText(
            datetime.now().strftime("当前时间 %H:%M:%S  "))

    def reset_counts(self):
        self.rx_count = 0
        self.tx_count = 0
        self._update_status()

    def _update_status(self):
        self.count_label.setText(f"RX: {self.rx_count}  TX: {self.tx_count}  ")

    def closeEvent(self, event):
        self._save_single_send()
        self.close_port()
        self.multi_page.save()
        super().closeEvent(event)
