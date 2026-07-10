"""主窗口：日志接收区 + 单条/多条发送页签 + 状态栏。"""

from __future__ import annotations

import codecs
import os
from datetime import datetime

import serial
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QTabWidget, QHBoxLayout, QVBoxLayout, QGridLayout,
    QGroupBox, QLabel, QComboBox, QPushButton, QCheckBox, QSpinBox,
    QPlainTextEdit, QMessageBox, QFileDialog, QSplitter, QApplication,
    QLineEdit, QProgressBar,
)

from .icon import app_icon
from .serial_manager import SerialManager, list_ports
from .multi_send import MultiSendPage
from .theme import Backdrop, apply_theme

BAUDRATES = ["1200", "2400", "4800", "9600", "19200", "38400", "57600",
             "115200", "230400", "460800", "921600"]
RX_BUFFER_LIMIT = 1024 * 1024       # 接收缓冲上限 1MB
DISPLAY_CHAR_LIMIT = 8 * 1024 * 1024  # 显示文本超过该字符数时按缓冲重渲染
FILE_SEND_CHUNK = 64 * 1024


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

        self._build_ui()
        apply_theme(self)
        self._reset_decoder()
        self.refresh_ports()
        self._update_status()

    # ---------- UI 构建 ----------

    def _build_ui(self):
        self.multi_page = MultiSendPage(self.send_data)
        self.setCentralWidget(self._build_main_page())

        self.status_label = QLabel()
        self.count_label = QLabel()
        self.clock_label = QLabel()
        reset_btn = QPushButton("复位计数")
        reset_btn.clicked.connect(self.reset_counts)
        sb = self.statusBar()
        sb.addWidget(self.status_label, 1)
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
        self.open_btn.setObjectName("primary")
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
        for w in (self.hex_recv_chk, self.timestamp_chk, self.pause_chk):
            recv_ctrl.addWidget(w)
        recv_btn_row = QHBoxLayout()
        recv_btn_row.addWidget(save_btn)
        recv_btn_row.addWidget(clear_recv_btn)
        recv_ctrl.addLayout(recv_btn_row)
        recv_box = QGroupBox("接收设置")
        recv_box.setLayout(recv_ctrl)

        right = QVBoxLayout()
        right.addWidget(settings_box)
        right.addWidget(recv_box)
        right.addWidget(self.multi_page.controls_box)
        right.addStretch()

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
        send_btn.setFixedSize(80, 55)
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
        layout.setContentsMargins(10, 10, 10, 6)
        layout.addWidget(splitter, 1)
        layout.addLayout(right)
        page = Backdrop()
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
                    self.status_label.setText(f"发送文件 {sent}/{total} 字节")
                    QApplication.processEvents()
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
        if self.sm.is_open:
            self.status_label.setText(
                f"已打开 {self.sm.ser.port} @ {self.sm.ser.baudrate}")
        else:
            self.status_label.setText("串口已关闭")
        self.count_label.setText(f"RX: {self.rx_count}  TX: {self.tx_count}  ")

    def closeEvent(self, event):
        self.close_port()
        self.multi_page.save()
        super().closeEvent(event)
