"""Dialog for capturing a new signature or initial by freehand drawing."""
from PySide6.QtCore import QEvent, QPointF, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

PAD_SIZE = (560, 220)


class SignaturePad(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(*PAD_SIZE)
        self.image = QImage(self.size(), QImage.Format_ARGB32_Premultiplied)
        self.image.fill(Qt.transparent)
        self._drawing = False
        self._last_point = None
        self._has_ink = False
        self.setStyleSheet("background: white; border: 1px solid #999;")

    def clear(self):
        self.image.fill(Qt.transparent)
        self._has_ink = False
        self.update()

    def has_ink(self):
        return self._has_ink

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), Qt.white)
        painter.drawImage(0, 0, self.image)

    def _draw_segment(self, p1, p2):
        painter = QPainter(self.image)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(10, 10, 10), 3.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(pen)
        if p1 == p2:
            painter.drawPoint(p2)
        else:
            painter.drawLine(p1, p2)
        painter.end()
        self._has_ink = True
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drawing = True
            self._last_point = event.position()
            self._draw_segment(self._last_point, self._last_point)

    def mouseMoveEvent(self, event):
        if self._drawing:
            pos = event.position()
            self._draw_segment(self._last_point, pos)
            self._last_point = pos

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drawing = False
            self._last_point = None

    def tabletEvent(self, event):
        etype = event.type()
        pos = event.position()
        if etype == QEvent.TabletPress:
            self._drawing = True
            self._last_point = pos
            self._draw_segment(pos, pos)
        elif etype == QEvent.TabletMove and self._drawing:
            self._draw_segment(self._last_point, pos)
            self._last_point = pos
        elif etype == QEvent.TabletRelease:
            self._drawing = False
            self._last_point = None
        event.accept()

    def cropped_image(self) -> QImage:
        """Trim transparent margins so the stamped signature is tightly sized."""
        bounds = QRect()
        w, h = self.image.width(), self.image.height()
        for y in range(h):
            for x in range(w):
                if self.image.pixelColor(x, y).alpha() > 10:
                    if bounds.isNull():
                        bounds = QRect(x, y, 1, 1)
                    else:
                        bounds = bounds.united(QRect(x, y, 1, 1))
        if bounds.isNull():
            return self.image.copy()
        pad = 6
        bounds = bounds.adjusted(-pad, -pad, pad, pad).intersected(self.image.rect())
        return self.image.copy(bounds)


class SignatureDialog(QDialog):
    def __init__(self, parent=None, default_type="signature"):
        super().__init__(parent)
        self.setWindowTitle("新建签名")
        self.result_item = None
        self._store = parent.signature_store if parent is not None else None

        layout = QVBoxLayout(self)

        hint = QLabel("请在下方区域用鼠标或触控笔书写签名：")
        layout.addWidget(hint)

        self.pad = SignaturePad(self)
        layout.addWidget(self.pad)

        clear_btn = QPushButton("清除重写")
        clear_btn.clicked.connect(self.pad.clear)
        layout.addWidget(clear_btn)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("名称："))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("例如：常用签名 / 花押")
        name_row.addWidget(self.name_edit)
        layout.addLayout(name_row)

        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("类型："))
        self.radio_signature = QRadioButton("完整签名")
        self.radio_initial = QRadioButton("缩写 (Initial)")
        if default_type == "initial":
            self.radio_initial.setChecked(True)
        else:
            self.radio_signature.setChecked(True)
        type_row.addWidget(self.radio_signature)
        type_row.addWidget(self.radio_initial)
        type_row.addStretch(1)
        layout.addLayout(type_row)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("保存")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    def _on_save(self):
        if not self.pad.has_ink():
            QMessageBox.warning(self, "提示", "请先书写签名内容。")
            return
        sig_type = "initial" if self.radio_initial.isChecked() else "signature"
        name = self.name_edit.text().strip()
        cropped = self.pad.cropped_image()
        self.result_item = {"image": cropped, "name": name, "type": sig_type}
        self.accept()
