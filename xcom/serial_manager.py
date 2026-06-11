"""串口管理：打开/关闭串口、后台收数线程。"""

import serial
import serial.tools.list_ports
from PySide6.QtCore import QThread, Signal


def list_ports():
    """枚举系统串口，返回 [(device, description), ...]"""
    return [(p.device, p.description) for p in serial.tools.list_ports.comports()]


PARITY_MAP = {
    "无": serial.PARITY_NONE,
    "奇": serial.PARITY_ODD,
    "偶": serial.PARITY_EVEN,
    "Mark": serial.PARITY_MARK,
    "Space": serial.PARITY_SPACE,
}

STOPBITS_MAP = {
    "1": serial.STOPBITS_ONE,
    "1.5": serial.STOPBITS_ONE_POINT_FIVE,
    "2": serial.STOPBITS_TWO,
}


class SerialWorker(QThread):
    """后台收数线程：循环读串口，数据通过信号发回主线程。"""

    data_received = Signal(bytes)
    error_occurred = Signal(str)

    def __init__(self, ser: serial.Serial, parent=None):
        super().__init__(parent)
        self._ser = ser
        self._running = True

    def run(self):
        while self._running:
            try:
                n = self._ser.in_waiting
                data = self._ser.read(n if n else 1)
            except (serial.SerialException, OSError) as e:
                if self._running:
                    self.error_occurred.emit(str(e))
                break
            if data:
                self.data_received.emit(data)

    def stop(self):
        self._running = False
        self.wait(1000)


class SerialManager:
    """持有串口对象与收数线程。"""

    def __init__(self):
        self.ser: serial.Serial | None = None
        self.worker: SerialWorker | None = None

    @property
    def is_open(self) -> bool:
        return self.ser is not None and self.ser.is_open

    def open(self, port, baudrate, bytesize, stopbits, parity, flow,
             on_data, on_error):
        ser = serial.Serial()
        ser.port = port
        ser.baudrate = baudrate
        ser.bytesize = bytesize
        ser.stopbits = STOPBITS_MAP[stopbits]
        ser.parity = PARITY_MAP[parity]
        ser.timeout = 0.05
        ser.rtscts = flow == "RTS/CTS"
        ser.xonxoff = flow == "XON/XOFF"
        ser.open()
        self.ser = ser

        self.worker = SerialWorker(ser)
        self.worker.data_received.connect(on_data)
        self.worker.error_occurred.connect(on_error)
        self.worker.start()

    def close(self):
        if self.worker:
            self.worker.stop()
            self.worker = None
        if self.ser:
            try:
                self.ser.close()
            except (serial.SerialException, OSError):
                pass
            self.ser = None

    def write(self, data: bytes) -> int:
        if not self.is_open:
            raise serial.SerialException("串口未打开")
        return self.ser.write(data)

    def set_dtr(self, on: bool):
        if self.is_open:
            self.ser.dtr = on

    def set_rts(self, on: bool):
        if self.is_open:
            self.ser.rts = on
