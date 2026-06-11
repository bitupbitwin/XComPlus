"""主窗口：串口收发页签 + 多条发送页签 + 状态栏。"""

from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QTabWidget, QHBoxLayout, QVBoxLayout, QGridLayout,
    QGroupBox, QLabel, QComboBox, QPushButton, QCheckBox, QSpinBox,
    QPlainTextEdit, QMessageBox, QFileDialog,
)

from .serial_manager import SerialManager, list_ports
from .multi_send import MultiSendPage

BAUDRATES = ["1200", "2400", "4800", "9600", "19200", "38400", "57600",
             "115200", "230400", "460800", "921600"]
RX_BUFFER_LIMIT = 1024 * 1024  # 接收缓冲上限 1MB


def parse_hex(text: str) -> bytes:
    """解析 "AA BB 0F" 形式的 16 进制字符串，非法时抛 ValueError。"""
    s = "".join(text.split())
    if len(s) % 2 != 0:
        raise ValueError("16进制数据长度必须为偶数个字符")
    return bytes.fromhex(s)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("X-COM+ 串口调试助手")
        self.resize(960, 640)

        self.sm = SerialManager()
        self.rx_chunks = []      # [(datetime, bytes), ...]
        self.rx_buffer_size = 0
        self.rx_count = 0
        self.tx_count = 0
        self.display_paused = False

        self._build_ui()
        self.refresh_ports()
        self._update_status()

    # ---------- UI 构建 ----------

    def _build_ui(self):
        tabs = QTabWidget()
        tabs.addTab(self._build_main_page(), "串口数据收发")
        self.multi_page = MultiSendPage(self.send_data)
        tabs.addTab(self.multi_page, "多条数据发送")
        self.setCentralWidget(tabs)

        self.status_label = QLabel()
        self.count_label = QLabel()
        reset_btn = QPushButton("复位计数")
        reset_btn.clicked.connect(self.reset_counts)
        sb = self.statusBar()
        sb.addWidget(self.status_label, 1)
        sb.addPermanentWidget(self.count_label)
        sb.addPermanentWidget(reset_btn)

    def _build_main_page(self) -> QWidget:
        # 接收区
        self.recv_text = QPlainTextEdit()
        self.recv_text.setReadOnly(True)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.Monospace)
        self.recv_text.setFont(mono)

        # 右侧串口设置
        self.port_combo = QComboBox()
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self.refresh_ports)
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(BAUDRATES)
        self.baud_combo.setCurrentText("115200")
        self.baud_combo.setEditable(True)
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
        self.open_btn.clicked.connect(self.toggle_port)

        grid = QGridLayout()
        rows = [
            ("串口选择", self.port_combo),
            ("波特率", self.baud_combo),
            ("停止位", self.stop_combo),
            ("数据位", self.data_combo),
            ("校验位", self.parity_combo),
            ("流控", self.flow_combo),
            ("编码", self.encoding_combo),
        ]
        for r, (name, w) in enumerate(rows):
            grid.addWidget(QLabel(name), r, 0)
            grid.addWidget(w, r, 1)
        grid.addWidget(refresh_btn, 0, 2)
        grid.addWidget(self.open_btn, len(rows), 0, 1, 3)

        self.dtr_chk = QCheckBox("DTR")
        self.dtr_chk.toggled.connect(lambda on: self.sm.set_dtr(on))
        self.rts_chk = QCheckBox("RTS")
        self.rts_chk.toggled.connect(lambda on: self.sm.set_rts(on))
        dtr_rts = QHBoxLayout()
        dtr_rts.addWidget(self.dtr_chk)
        dtr_rts.addWidget(self.rts_chk)
        grid.addLayout(dtr_rts, len(rows) + 1, 0, 1, 3)

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
        for w in (self.hex_recv_chk, self.timestamp_chk, self.pause_chk,
                  save_btn, clear_recv_btn):
            recv_ctrl.addWidget(w)
        recv_box = QGroupBox("接收设置")
        recv_box.setLayout(recv_ctrl)

        right = QVBoxLayout()
        right.addWidget(settings_box)
        right.addWidget(recv_box)
        right.addStretch()

        # 发送区
        self.send_text = QPlainTextEdit()
        self.send_text.setFixedHeight(90)
        self.hex_send_chk = QCheckBox("16进制发送")
        self.newline_chk = QCheckBox("发送新行")
        self.timer_send_chk = QCheckBox("定时发送")
        self.timer_send_chk.toggled.connect(self._toggle_timer_send)
        self.period_spin = QSpinBox()
        self.period_spin.setRange(1, 600000)
        self.period_spin.setValue(1000)
        self.period_spin.setSuffix(" ms")
        send_btn = QPushButton("发送")
        send_btn.setFixedHeight(60)
        send_btn.clicked.connect(self.send_current)
        send_file_btn = QPushButton("发送文件")
        send_file_btn.clicked.connect(self.send_file)
        clear_send_btn = QPushButton("清除发送")
        clear_send_btn.clicked.connect(self.send_text.clear)

        send_opts = QVBoxLayout()
        send_opts.addWidget(self.hex_send_chk)
        send_opts.addWidget(self.newline_chk)
        timer_row = QHBoxLayout()
        timer_row.addWidget(self.timer_send_chk)
        timer_row.addWidget(self.period_spin)
        send_opts.addLayout(timer_row)
        btn_row = QHBoxLayout()
        btn_row.addWidget(send_file_btn)
        btn_row.addWidget(clear_send_btn)
        send_opts.addLayout(btn_row)

        send_layout = QHBoxLayout()
        send_layout.addWidget(self.send_text, 1)
        send_layout.addLayout(send_opts)
        send_layout.addWidget(send_btn)
        send_box = QGroupBox("发送")
        send_box.setLayout(send_layout)

        left = QVBoxLayout()
        left.addWidget(self.recv_text, 1)
        left.addWidget(send_box)

        layout = QHBoxLayout()
        layout.addLayout(left, 1)
        layout.addLayout(right)
        page = QWidget()
        page.setLayout(layout)

        self.send_timer = QTimer(self)
        self.send_timer.timeout.connect(self._timer_send_tick)
        return page

    # ---------- 串口开关 ----------

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
        self.open_btn.setText("关闭串口")
        self._set_settings_enabled(False)
        self._update_status()

    def close_port(self):
        self.send_timer.stop()
        self.timer_send_chk.setChecked(False)
        self.multi_page.stop_cycle()
        self.sm.close()
        self.open_btn.setText("打开串口")
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
        self._update_status()

    def _format_chunk(self, ts: datetime, data: bytes) -> str:
        if self.hex_recv_chk.isChecked():
            body = " ".join(f"{b:02X}" for b in data) + " "
        else:
            body = data.decode(self.encoding_combo.currentText(),
                               errors="replace")
        if self.timestamp_chk.isChecked():
            return f"\n[{ts.strftime('%H:%M:%S.%f')[:-3]}] {body}"
        return body

    def _append_text(self, text: str):
        cursor = self.recv_text.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(text)
        self.recv_text.setTextCursor(cursor)

    def rerender_recv(self):
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

    def send_data(self, text: str, is_hex: bool, newline: bool = False) -> bool:
        """所有发送的统一出口，返回是否发送成功。"""
        if not self.sm.is_open:
            QMessageBox.warning(self, "提示", "串口未打开")
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
        except ValueError as e:
            QMessageBox.warning(self, "16进制格式错误", str(e))
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
        self.send_timer.setInterval(self.period_spin.value())
        if not self.send_current():
            self.timer_send_chk.setChecked(False)

    def send_file(self):
        if not self.sm.is_open:
            QMessageBox.warning(self, "提示", "串口未打开")
            return
        path, _ = QFileDialog.getOpenFileName(self, "发送文件")
        if not path:
            return
        try:
            with open(path, "rb") as f:
                data = f.read()
            self.sm.write(data)
        except Exception as e:
            QMessageBox.critical(self, "发送文件失败", str(e))
            return
        self.tx_count += len(data)
        self._update_status()

    # ---------- 状态栏 ----------

    def reset_counts(self):
        self.rx_count = 0
        self.tx_count = 0
        self._update_status()

    def _update_status(self):
        if self.sm.is_open:
            self.status_label.setText(
                f"已打开 {self.sm.ser.port} @ {self.sm.ser.baudrate}")
        else:
            self.status_label.setText("串口已关闭")
        self.count_label.setText(f"RX: {self.rx_count}  TX: {self.tx_count}  ")

    def closeEvent(self, event):
        self.close_port()
        super().closeEvent(event)
