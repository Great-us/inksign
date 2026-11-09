"""A small, consistent line-art icon set for the toolbar (Adobe-Reader-style:
flat monochrome glyphs, tooltips carry the label instead of on-canvas text).

Every icon is drawn on a square canvas with the same stroke weight so the
whole toolbar reads as one coherent set rather than mismatched glyphs.
"""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

INK = QColor("#37474F")
ACCENT_YELLOW = QColor("#FDD835")
CANVAS = 32


def _canvas():
    pix = QPixmap(CANVAS, CANVAS)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)
    return pix, painter


def _stroke(painter, color=INK, width=2.3):
    pen = QPen(color, width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    return pen


def _finish(pix, painter) -> QIcon:
    painter.end()
    return QIcon(pix)


def icon_open() -> QIcon:
    pix, p = _canvas()
    _stroke(p)
    p.drawRoundedRect(QRectF(5, 8, 10, 5), 1.5, 1.5)
    p.drawRoundedRect(QRectF(5, 11, 22, 14), 2, 2)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#90A4AE"))
    p.drawPolygon([QPointF(6, 15), QPointF(27, 15), QPointF(24, 25), QPointF(9, 25)])
    return _finish(pix, p)


def icon_save() -> QIcon:
    pix, p = _canvas()
    _stroke(p)
    p.drawRoundedRect(QRectF(5, 5, 22, 22), 3, 3)
    p.drawRect(QRectF(10, 5.5, 8, 6))
    p.drawRoundedRect(QRectF(8.5, 16, 15, 9), 1, 1)
    return _finish(pix, p)


def icon_select() -> QIcon:
    """Text-cursor (I-beam) glyph — the tool selects/copies text."""
    pix, p = _canvas()
    _stroke(p, width=2.4)
    p.drawLine(QPointF(16, 6), QPointF(16, 26))
    p.drawLine(QPointF(11, 6), QPointF(21, 6))
    p.drawLine(QPointF(11, 26), QPointF(21, 26))
    return _finish(pix, p)


def icon_hand() -> QIcon:
    pix, p = _canvas()
    _stroke(p, width=2.1)
    p.drawRoundedRect(QRectF(9, 16, 14, 11), 4, 4)
    for i, x in enumerate([11, 15.3, 19.6, 23.9]):
        top = 6 + (0 if i in (1, 2) else 3)
        p.drawRoundedRect(QRectF(x, top, 3.4, 16 - top + 3), 1.6, 1.6)
    return _finish(pix, p)


def icon_pen() -> QIcon:
    pix, p = _canvas()
    p.translate(16, 16)
    p.rotate(-45)
    _stroke(p, width=2.0)
    p.drawRoundedRect(QRectF(-3, -13, 6, 16), 2, 2)
    p.setPen(Qt.NoPen)
    p.setBrush(INK)
    p.drawPolygon([QPointF(-3, 3), QPointF(3, 3), QPointF(0, 12)])
    p.setBrush(QColor("#607D8B"))
    p.drawEllipse(QPointF(0, 13.5), 1.3, 1.3)
    return _finish(pix, p)


def icon_highlighter() -> QIcon:
    pix, p = _canvas()
    p.translate(16, 16)
    p.rotate(-45)
    _stroke(p, width=2.0)
    p.drawRoundedRect(QRectF(-4, -12, 8, 13), 1.5, 1.5)
    p.setPen(Qt.NoPen)
    p.setBrush(ACCENT_YELLOW)
    p.drawPolygon([QPointF(-4, 1), QPointF(4, 1), QPointF(4, 6), QPointF(-4, 6)])
    p.setBrush(INK)
    p.drawPolygon([QPointF(-4, 6), QPointF(4, 6), QPointF(0, 13)])
    return _finish(pix, p)


def icon_undo() -> QIcon:
    pix, p = _canvas()
    _stroke(p, width=2.3)
    rect = QRectF(7, 8, 17, 17)
    p.drawArc(rect, 20 * 16, 300 * 16)
    ang = math.radians(20)
    tip = QPointF(rect.center().x() + rect.width() / 2 * math.cos(ang), rect.center().y() - rect.height() / 2 * math.sin(ang))
    p.setPen(Qt.NoPen)
    p.setBrush(INK)
    p.drawPolygon([tip + QPointF(-1, -6), tip + QPointF(6, -1), tip + QPointF(-1.5, 4)])
    return _finish(pix, p)


def icon_clear() -> QIcon:
    pix, p = _canvas()
    _stroke(p, width=2.1)
    p.drawLine(QPointF(8, 10), QPointF(24, 10))
    p.drawLine(QPointF(13, 10), QPointF(13.5, 6.5))
    p.drawLine(QPointF(19, 10), QPointF(18.5, 6.5))
    p.drawLine(QPointF(13.5, 6.5), QPointF(18.5, 6.5))
    p.drawRoundedRect(QRectF(9.5, 10, 13, 15), 1.5, 1.5)
    p.drawLine(QPointF(13, 13.5), QPointF(13, 22))
    p.drawLine(QPointF(16, 13.5), QPointF(16, 22))
    p.drawLine(QPointF(19, 13.5), QPointF(19, 22))
    return _finish(pix, p)


def _magnifier(p):
    _stroke(p, width=2.3)
    p.drawEllipse(QRectF(6, 6, 14, 14))
    p.drawLine(QPointF(21, 21), QPointF(26.5, 26.5))


def icon_zoom_out() -> QIcon:
    pix, p = _canvas()
    _magnifier(p)
    p.drawLine(QPointF(9.5, 13), QPointF(16.5, 13))
    return _finish(pix, p)


def icon_zoom_in() -> QIcon:
    pix, p = _canvas()
    _magnifier(p)
    p.drawLine(QPointF(9.5, 13), QPointF(16.5, 13))
    p.drawLine(QPointF(13, 9.5), QPointF(13, 16.5))
    return _finish(pix, p)


def icon_zoom_reset() -> QIcon:
    """'Fit' corner-brackets glyph, the standard reset-zoom convention."""
    pix, p = _canvas()
    _stroke(p, width=2.3)
    d = 6
    corners = [(7, 7, 1, 1), (25, 7, -1, 1), (7, 25, 1, -1), (25, 25, -1, -1)]
    for x, y, sx, sy in corners:
        p.drawLine(QPointF(x, y), QPointF(x + d * sx, y))
        p.drawLine(QPointF(x, y), QPointF(x, y + d * sy))
    return _finish(pix, p)


def icon_signature() -> QIcon:
    pix, p = _canvas()
    _stroke(p, width=2.4)
    path = QPainterPath()
    path.moveTo(5, 21)
    path.cubicTo(8, 12, 11, 12, 12, 19)
    path.cubicTo(13, 24, 15, 20, 16, 15)
    path.cubicTo(17, 10, 19, 10, 20, 17)
    path.cubicTo(21, 22, 23, 19, 27, 12)
    p.drawPath(path)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#E11D48"))
    p.drawEllipse(QPointF(27, 12), 1.6, 1.6)
    return _finish(pix, p)


def icon_pen_tip_badge() -> QIcon:
    pix, p = _canvas()
    p.translate(16, 16)
    p.rotate(-45)
    p.setPen(Qt.NoPen)
    p.setBrush(INK)
    p.drawPolygon([QPointF(-4, -8), QPointF(4, -8), QPointF(0, 8)])
    return _finish(pix, p)


def icon_droplet_badge() -> QIcon:
    pix, p = _canvas()
    _stroke(p, width=2.0)
    path = QPainterPath()
    path.moveTo(16, 6)
    path.cubicTo(22, 15, 24, 19, 24, 22)
    path.cubicTo(24, 27, 20, 27, 16, 27)
    path.cubicTo(12, 27, 8, 27, 8, 22)
    path.cubicTo(8, 19, 10, 15, 16, 6)
    path.closeSubpath()
    p.drawPath(path)
    return _finish(pix, p)


def icon_thickness_badge() -> QIcon:
    pix, p = _canvas()
    p.setPen(Qt.NoPen)
    p.setBrush(INK)
    heights = [1.6, 2.8, 4.2]
    y = 10
    for h in heights:
        p.drawRoundedRect(QRectF(7, y, 18, h), h / 2, h / 2)
        y += h + 3.5
    return _finish(pix, p)
