"""应用图标：球拍·信号 —— 毛玻璃底上乒乓球拍，拍面刻串口方波。

运行时矢量绘制，任意尺寸清晰；小尺寸自动省略细节保证辨识度。
"""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QIcon, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap, QRadialGradient)

SIZES = (16, 24, 32, 48, 64, 128, 256)

ORANGE = QColor("#FF9500")
ORANGE_L = QColor("#FFB04D")
INK = QColor("#2A1804")      # 深褐墨色
CREAM = QColor("#FFFDF6")


def _paint(size: int) -> QPixmap:
    s = float(size)
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)

    # 毛玻璃深色底 + 右上橙色光晕（与界面主题一致）
    body = QRectF(s * 0.04, s * 0.04, s * 0.92, s * 0.92)
    radius = s * 0.20
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#171921"))
    p.drawRoundedRect(body, radius, radius)
    glow = QRadialGradient(QPointF(s * 0.82, s * 0.16), s * 0.72)
    glow.setColorAt(0.0, QColor(255, 149, 0, 78))
    glow.setColorAt(1.0, QColor(255, 149, 0, 0))
    p.setBrush(glow)
    p.drawRoundedRect(body, radius, radius)
    p.setPen(QPen(QColor(255, 255, 255, 36), max(1.0, s * 0.008)))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(body, radius, radius)

    # 球拍（旋转 -35°）：实心胶皮拍面 + 短粗拍柄
    p.save()
    p.translate(QPointF(s * 0.44, s * 0.52))
    p.rotate(-35)
    br = s * 0.265
    bc = QPointF(0, -s * 0.05)

    # 拍柄：短粗、带肩，收口略窄
    handle = QPainterPath()
    hw_top, hw_bot, h_len = s * 0.105, s * 0.075, s * 0.245
    y0 = br * 0.78 + bc.y()
    handle.moveTo(-hw_top, y0)
    handle.lineTo(hw_top, y0)
    handle.lineTo(hw_bot, y0 + h_len)
    handle.quadTo(0, y0 + h_len + s * 0.045, -hw_bot, y0 + h_len)
    handle.closeSubpath()
    hg = QLinearGradient(0, y0, 0, y0 + h_len)
    hg.setColorAt(0.0, QColor("#E8890A"))
    hg.setColorAt(1.0, QColor("#C96F00"))
    p.setPen(Qt.NoPen)
    p.setBrush(hg)
    p.drawPath(handle)

    # 拍面：橙色胶皮（实心），外缘一圈深色包边
    rubber = QRadialGradient(QPointF(bc.x() - br * 0.35, bc.y() - br * 0.4),
                             br * 1.9)
    rubber.setColorAt(0.0, ORANGE_L)
    rubber.setColorAt(1.0, QColor("#F07D00"))
    p.setBrush(rubber)
    p.setPen(QPen(INK, max(1.0, s * 0.025)))
    p.drawEllipse(bc, br, br)

    # 拍面上的串口方波（墨色，小尺寸省略）
    if size >= 24:
        path = QPainterPath()
        pts = [(-0.62, 0.24), (-0.30, 0.24), (-0.30, -0.28), (0.04, -0.28),
               (0.04, 0.24), (0.34, 0.24), (0.34, -0.28), (0.64, -0.28)]
        path.moveTo(bc.x() + pts[0][0] * br, bc.y() + pts[0][1] * br)
        for x, y in pts[1:]:
            path.lineTo(bc.x() + x * br, bc.y() + y * br)
        pen = QPen(INK, s * 0.030, Qt.SolidLine, Qt.RoundCap)
        pen.setJoinStyle(Qt.MiterJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.setClipPath(_circle(bc, br * 0.88))
        p.drawPath(path)
        p.setClipping(False)
    p.restore()

    # 乒乓球 + 速度弧线
    ball = QPointF(s * 0.755, s * 0.255)
    shade = QRadialGradient(QPointF(ball.x() - s * 0.02, ball.y() - s * 0.02),
                            s * 0.10)
    shade.setColorAt(0.0, CREAM)
    shade.setColorAt(1.0, QColor("#E4D8BC"))
    p.setPen(Qt.NoPen)
    p.setBrush(shade)
    p.drawEllipse(ball, s * 0.066, s * 0.066)
    if size >= 24:
        p.setBrush(Qt.NoBrush)
        for i, alpha in ((1, 165), (2, 90)):
            pen = QPen(QColor(255, 149, 0, alpha), s * 0.018,
                       Qt.SolidLine, Qt.RoundCap)
            p.setPen(pen)
            rr = s * (0.105 + 0.055 * i)
            p.drawArc(QRectF(ball.x() - rr, ball.y() - rr, rr * 2, rr * 2),
                      140 * 16, 85 * 16)

    p.end()
    return pm


def _circle(c: QPointF, r: float) -> QPainterPath:
    path = QPainterPath()
    path.addEllipse(c, r, r)
    return path


def app_icon() -> QIcon:
    icon = QIcon()
    for s in SIZES:
        icon.addPixmap(_paint(s))
    return icon
