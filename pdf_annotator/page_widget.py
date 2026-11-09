"""A single PDF page: renders the page and hosts a transparent annotation
overlay that the user draws / highlights / erases / stamps signatures on.

Annotations are kept as an ordered list of lightweight "ops" (pen stroke /
highlight stroke / eraser stroke / signature stamp), replayed onto the
overlay image. This is what lets the Stroke Eraser find and delete a whole
stroke by touching it, and lets Undo restore prior states cheaply (it
snapshots the small ops list, not full images).
"""
import io
import math

import fitz  # PyMuPDF
from PySide6.QtCore import QEvent, QLineF, QPointF, QRectF, Qt, QSize
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QToolButton, QWidget

RENDER_SCALE = 2.0  # base raster resolution multiplier (~144 DPI); also the
                    # coordinate space annotations live in (points * RENDER_SCALE)
MAX_RENDER_RATIO = 3.0  # cap how much sharper than base a visible page may render
                        # (bounds memory: one page at ratio 3 ≈ 70 MB)
MAX_UNDO = 100
HANDLE_SIZE = 16
STROKE_ERASER_TOLERANCE = 6.0  # extra px (in overlay-pixel space) around a stroke that still counts as a hit


def _pixmap_to_qimage(pix: "fitz.Pixmap") -> QImage:
    fmt = QImage.Format_RGBA8888 if pix.alpha else QImage.Format_RGB888
    img = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt)
    return img.copy()


def _dist_point_to_segment(p: QPointF, a: QPointF, b: QPointF) -> float:
    dx, dy = b.x() - a.x(), b.y() - a.y()
    if dx == 0 and dy == 0:
        return QLineF(p, a).length()
    t = ((p.x() - a.x()) * dx + (p.y() - a.y()) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    closest = QPointF(a.x() + t * dx, a.y() + t * dy)
    return QLineF(p, closest).length()


class PageWidget(QWidget):
    def __init__(self, fitz_page: "fitz.Page", page_index: int, controller, parent=None):
        super().__init__(parent)
        self.page_index = page_index
        self.controller = controller

        self._fitz_page = fitz_page
        # _base_pixmap: always-kept low-res render (ratio 1.0 == today's quality,
        # ~8 MB). page_pixmap points either at it or a transient hi-res render.
        self._base_pixmap = self._render_at(RENDER_SCALE)
        self.base_size = self._base_pixmap.size()
        self.page_pixmap = self._base_pixmap
        self._pixmap_ratio = 1.0
        self.overlay = QImage(self.base_size, QImage.Format_ARGB32_Premultiplied)
        self.overlay.fill(Qt.transparent)

        self.page_rect_pts = (fitz_page.rect.width, fitz_page.rect.height)
        self.chars = self._extract_chars(fitz_page)

        self.display_scale = 1.0

        # Ordered list of {"kind": "pen"|"highlight"|"erase"|"stamp", ...}
        self.ops = []
        self._undo_stack = []  # snapshots of self.ops (cheap: shallow list copies)

        self._drawing = False
        self._last_point = None
        self._active_painter = None
        self._current_op = None

        self.pending_stamp = None  # {"image": QImage, "rect": QRectF}
        self._stamp_drag_mode = None  # None | "move" | "resize"
        self._stamp_drag_anchor = None
        self._stamp_orig_rect = None

        self.selection = None  # (start_char_index, end_char_index) or None
        self._sel_dragging = False
        self._sel_start = None
        self._pan_dragging = False
        self._pan_last_global = None

        self.setAttribute(Qt.WA_StaticContents, True)
        self.setMouseTracking(True)
        self.setFixedSize(self.base_size)

        self.btn_confirm = QToolButton(self)
        self.btn_confirm.setText("✓")
        self.btn_confirm.setToolTip("确认放置")
        self.btn_confirm.setFixedSize(28, 28)
        self.btn_confirm.setStyleSheet(
            "QToolButton{background:#2e7d32;color:white;border-radius:14px;font-weight:bold;}"
        )
        self.btn_confirm.clicked.connect(self._commit_stamp)
        self.btn_confirm.hide()

        self.btn_cancel = QToolButton(self)
        self.btn_cancel.setText("✕")
        self.btn_cancel.setToolTip("取消")
        self.btn_cancel.setFixedSize(28, 28)
        self.btn_cancel.setStyleSheet(
            "QToolButton{background:#c62828;color:white;border-radius:14px;font-weight:bold;}"
        )
        self.btn_cancel.clicked.connect(self._cancel_stamp)
        self.btn_cancel.hide()

    # ---------- page rasterization (on-demand, resolution tracks zoom) ----------
    def _render_at(self, effective_scale: float) -> QImage:
        mat = fitz.Matrix(effective_scale, effective_scale)
        pix = self._fitz_page.get_pixmap(matrix=mat, alpha=False)
        return _pixmap_to_qimage(pix)

    def ensure_render(self, display_ratio: float):
        """Render this page's bitmap sharp enough for the given on-screen ratio,
        re-rasterizing from the PDF's vectors (like Adobe) instead of upscaling a
        fixed bitmap. Called only for pages currently visible in the viewport."""
        if self._fitz_page is None:
            return
        # quantize to 0.5 steps so small zoom nudges don't trigger re-renders
        rc = min(MAX_RENDER_RATIO, math.ceil(max(display_ratio, 1.0) * 2) / 2)
        if rc <= 1.0:
            self.release_hires()
            return
        if abs(rc - self._pixmap_ratio) < 1e-6:
            return
        self.page_pixmap = self._render_at(RENDER_SCALE * rc)
        self._pixmap_ratio = rc
        self.update()

    def release_hires(self):
        """Drop the transient hi-res bitmap and fall back to the cached base
        render — instant (just a pointer swap) and frees the large image."""
        if self._pixmap_ratio != 1.0:
            self.page_pixmap = self._base_pixmap
            self._pixmap_ratio = 1.0
            self.update()

    def cleanup(self):
        """Break the reference to the fitz page before this widget is discarded
        (the owning document may be closed right after)."""
        self._fitz_page = None

    # ---------- zoom ----------
    def set_display_scale(self, scale: float):
        self.display_scale = scale
        self.setFixedSize(QSize(int(self.base_size.width() * scale), int(self.base_size.height() * scale)))
        self._update_stamp_buttons()
        self.update()

    def sizeHint(self):
        return self.size()

    # ---------- text layer (selection / copy) ----------
    @staticmethod
    def _extract_chars(fitz_page):
        """Per-character bounding boxes so selection works one glyph at a time —
        essential for CJK text, where get_text("words") lumps a whole run of
        characters with no whitespace into a single giant "word"."""
        chars = []
        raw = fitz_page.get_text("rawdict")
        for block_no, block in enumerate(raw.get("blocks", [])):
            if block.get("type") != 0:  # skip images
                continue
            for line_no, line in enumerate(block.get("lines", [])):
                for span in line.get("spans", []):
                    for ch in span.get("chars", []):
                        x0, y0, x1, y1 = ch["bbox"]
                        rect = QRectF(
                            x0 * RENDER_SCALE, y0 * RENDER_SCALE,
                            (x1 - x0) * RENDER_SCALE, (y1 - y0) * RENDER_SCALE,
                        )
                        chars.append({"rect": rect, "text": ch["c"], "line": (block_no, line_no)})
        return chars

    def _char_index_at(self, pt: QPointF):
        for i, c in enumerate(self.chars):
            if c["rect"].contains(pt):
                return i
        return None

    def _char_index_near(self, pt: QPointF):
        if not self.chars:
            return None
        idx = self._char_index_at(pt)
        if idx is not None:
            return idx
        best_i, best_key = None, None
        for i, c in enumerate(self.chars):
            r = c["rect"]
            vdist = 0.0 if r.top() <= pt.y() <= r.bottom() else min(abs(pt.y() - r.top()), abs(pt.y() - r.bottom()))
            hdist = 0.0 if r.left() <= pt.x() <= r.right() else min(abs(pt.x() - r.left()), abs(pt.x() - r.right()))
            key = (vdist, hdist)
            if best_key is None or key < best_key:
                best_key, best_i = key, i
        return best_i

    def _update_selection(self, start_pt: QPointF, end_pt: QPointF):
        idx_a = self._char_index_near(start_pt)
        idx_b = self._char_index_near(end_pt)
        if idx_a is None or idx_b is None:
            self.selection = None
        else:
            self.selection = (min(idx_a, idx_b), max(idx_a, idx_b))
        self.update()

    def selected_text(self) -> str:
        if self.selection is None:
            return ""
        lo, hi = self.selection
        parts = []
        prev_line = None
        for i in range(lo, hi + 1):
            c = self.chars[i]
            if prev_line is not None and c["line"] != prev_line:
                parts.append("\n")
            parts.append(c["text"])
            prev_line = c["line"]
        return "".join(parts)

    def copy_selection(self):
        text = self.selected_text()
        if text:
            QGuiApplication.clipboard().setText(text)
            self.controller.statusBar().showMessage("已复制选中文字", 2000)

    def clear_selection(self):
        if self.selection is not None:
            self.selection = None
            self.update()

    # ---------- painting ----------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        # page background: the hi-res raster stretched to fill the widget; when
        # its render ratio matches the zoom this is ~1:1 and stays crisp
        painter.drawImage(QRectF(0, 0, self.width(), self.height()), self.page_pixmap)
        # annotations + selection + pending stamp live in base (logical) space
        painter.scale(self.display_scale, self.display_scale)
        painter.drawImage(0, 0, self.overlay)

        if self.selection is not None:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(33, 150, 243, 90))
            lo, hi = self.selection
            for i in range(lo, hi + 1):
                painter.drawRect(self.chars[i]["rect"])

        if self.pending_stamp is not None:
            rect = self.pending_stamp["rect"]
            painter.drawImage(rect, self.pending_stamp["image"])
            pen = QPen(QColor(30, 136, 229), 2 / self.display_scale, Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect)
            handle_rect = self._handle_rect(rect)
            painter.setBrush(QColor(30, 136, 229))
            painter.drawRect(handle_rect)

    def _handle_rect(self, rect: QRectF) -> QRectF:
        s = HANDLE_SIZE / self.display_scale
        return QRectF(rect.right() - s, rect.bottom() - s, s, s)

    # ---------- undo ----------
    def _push_undo(self):
        self._undo_stack.append(list(self.ops))
        if len(self._undo_stack) > MAX_UNDO:
            self._undo_stack.pop(0)

    def undo(self):
        if not self._undo_stack:
            return
        self.ops = self._undo_stack.pop()
        self._rebuild_overlay()

    def clear_page(self):
        if not self.ops:
            return
        self._push_undo()
        self.ops = []
        self.overlay.fill(Qt.transparent)
        self.update()

    # ---------- coordinate helpers ----------
    def _to_overlay_pt(self, widget_pos: QPointF) -> QPointF:
        return QPointF(widget_pos.x() / self.display_scale, widget_pos.y() / self.display_scale)

    # ---------- op replay (used by undo / stroke-eraser deletion) ----------
    def _rebuild_overlay(self):
        img = QImage(self.base_size, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        painter = QPainter(img)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        for op in self.ops:
            self._paint_op_full(painter, op)
        painter.end()
        self.overlay = img
        self.update()

    def _paint_op_full(self, painter: QPainter, op: dict):
        if op["kind"] == "stamp":
            painter.setOpacity(1.0)
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            painter.drawImage(op["rect"], op["image"])
            return
        pts = op["points"]
        if len(pts) == 1:
            self._draw_op_point(painter, op, 0)
        else:
            for i in range(len(pts) - 1):
                self._draw_op_segment(painter, op, i, i + 1)

    def _configure_painter_for_op(self, painter: QPainter, op: dict):
        painter.setOpacity(op["opacity"])
        if op["kind"] == "erase":
            painter.setCompositionMode(QPainter.CompositionMode_Clear)
        else:
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)

    def _op_pen(self, op: dict, width: float) -> QPen:
        color = QColor(0, 0, 0, 255) if op["kind"] == "erase" else op["color"]
        pen = QPen(color, max(width, 1.0))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        return pen

    def _draw_op_point(self, painter: QPainter, op: dict, i: int):
        self._configure_painter_for_op(painter, op)
        painter.setPen(self._op_pen(op, op["widths"][i]))
        painter.drawPoint(op["points"][i])

    def _draw_op_segment(self, painter: QPainter, op: dict, i0: int, i1: int):
        self._configure_painter_for_op(painter, op)
        width = (op["widths"][i0] + op["widths"][i1]) / 2
        painter.setPen(self._op_pen(op, width))
        painter.drawLine(op["points"][i0], op["points"][i1])

    # ---------- stroke drawing (pen / highlight / eraser) ----------
    def _tool_width(self, pressure: float) -> float:
        tool = self.controller.tool
        if tool == "pen":
            return max(self.controller.pen_width * (0.5 + 0.5 * pressure), 1.0)
        elif tool == "highlight":
            return max(self.controller.highlight_width, 1.0)
        return max(self.controller.eraser_width, 1.0)  # pixel eraser

    def _begin_stroke(self, pos: QPointF, pressure: float):
        self._push_undo()
        self._drawing = True
        self._last_point = pos
        tool = self.controller.tool
        if tool == "pen":
            kind, color, opacity = "pen", QColor(self.controller.pen_color), 1.0
        elif tool == "highlight":
            kind, color, opacity = "highlight", QColor(self.controller.highlight_color), self.controller.highlight_opacity
        else:
            kind, color, opacity = "erase", QColor(0, 0, 0, 255), 1.0
        width0 = self._tool_width(pressure)
        self._current_op = {"kind": kind, "color": color, "opacity": opacity, "points": [pos], "widths": [width0]}

        painter = QPainter(self.overlay)
        painter.setRenderHint(QPainter.Antialiasing)
        self._draw_op_point(painter, self._current_op, 0)
        self._active_painter = painter
        self.update()

    def _continue_stroke(self, pos: QPointF, pressure: float):
        if not self._drawing or self._active_painter is None or self._current_op is None:
            return
        width = self._tool_width(pressure)
        self._current_op["points"].append(pos)
        self._current_op["widths"].append(width)
        i1 = len(self._current_op["points"]) - 1
        self._draw_op_segment(self._active_painter, self._current_op, i1 - 1, i1)
        self._last_point = pos
        self.update()

    def _end_stroke(self):
        if self._active_painter is not None:
            self._active_painter.end()
            self._active_painter = None
        if self._current_op is not None:
            self.ops.append(self._current_op)
            self._current_op = None
        self._drawing = False
        self._last_point = None

    # ---------- stroke eraser (deletes a whole pen/highlight stroke) ----------
    def _stroke_hit_test(self, pt: QPointF):
        tolerance = STROKE_ERASER_TOLERANCE + self.controller.eraser_width / 2
        for i in range(len(self.ops) - 1, -1, -1):  # topmost (most recently drawn) first
            op = self.ops[i]
            if op["kind"] not in ("pen", "highlight"):
                continue
            pts, widths = op["points"], op["widths"]
            if len(pts) == 1:
                if QLineF(pt, pts[0]).length() <= widths[0] / 2 + tolerance:
                    return i
                continue
            for j in range(len(pts) - 1):
                reach = max(widths[j], widths[j + 1]) / 2 + tolerance
                if _dist_point_to_segment(pt, pts[j], pts[j + 1]) <= reach:
                    return i
        return None

    def erase_stroke_at(self, pos: QPointF):
        idx = self._stroke_hit_test(pos)
        if idx is None:
            return
        self._push_undo()
        del self.ops[idx]
        self._rebuild_overlay()

    # ---------- stamp placement ----------
    def start_stamp(self, image: QImage, center_widget_pos: QPointF):
        aspect = image.width() / max(image.height(), 1)
        target_w = min(220.0, self.base_size.width() * 0.4)
        target_h = target_w / aspect
        center = self._to_overlay_pt(center_widget_pos)
        rect = QRectF(center.x() - target_w / 2, center.y() - target_h / 2, target_w, target_h)
        self.pending_stamp = {"image": image, "rect": rect}
        self._update_stamp_buttons()
        self.update()

    def cancel_pending_stamp(self):
        if self.pending_stamp is not None:
            self.pending_stamp = None
            self.btn_confirm.hide()
            self.btn_cancel.hide()
            self.update()

    def _cancel_stamp(self):
        self.cancel_pending_stamp()
        self.controller.on_stamp_ended()

    def _commit_stamp(self):
        if self.pending_stamp is None:
            return
        self._push_undo()
        op = {"kind": "stamp", "image": self.pending_stamp["image"], "rect": QRectF(self.pending_stamp["rect"])}
        self.ops.append(op)
        painter = QPainter(self.overlay)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.drawImage(op["rect"], op["image"])
        painter.end()
        self.pending_stamp = None
        self.btn_confirm.hide()
        self.btn_cancel.hide()
        self.update()
        self.controller.on_stamp_ended()

    def _update_stamp_buttons(self):
        if self.pending_stamp is None:
            self.btn_confirm.hide()
            self.btn_cancel.hide()
            return
        rect = self.pending_stamp["rect"]
        top_right_x = rect.right() * self.display_scale
        top_y = rect.top() * self.display_scale
        self.btn_cancel.move(int(top_right_x - 28), int(top_y - 34))
        self.btn_confirm.move(int(top_right_x - 62), int(top_y - 34))
        self.btn_confirm.show()
        self.btn_cancel.show()
        self.btn_confirm.raise_()
        self.btn_cancel.raise_()

    # ---------- export ----------
    def overlay_png_bytes(self) -> bytes:
        from PySide6.QtCore import QBuffer, QIODevice
        qbuf = QBuffer()
        qbuf.open(QIODevice.WriteOnly)
        self.overlay.save(qbuf, "PNG")
        data = bytes(qbuf.data())
        qbuf.close()
        return data

    # ---------- events ----------
    def _pointer_down(self, pos: QPointF, pressure: float):
        self.controller.set_active_page(self)
        tool = self.controller.tool
        if tool == "select":
            self.controller.clear_other_page_selections(self)
            self._sel_dragging = True
            self._sel_start = self._to_overlay_pt(pos)
            self.selection = None
            self.update()
        elif tool == "stroke_eraser":
            self._drawing = True
            self.erase_stroke_at(self._to_overlay_pt(pos))
        elif tool == "stamp":
            if self.pending_stamp is not None:
                self._handle_stamp_press(pos)
            elif self.controller.armed_signature is not None:
                image = self.controller.load_armed_signature_image()
                if image is not None and not image.isNull():
                    self.controller.set_active_stamp_page(self)
                    self.start_stamp(image, pos)
                    self._update_stamp_buttons()
        elif tool in ("pen", "highlight", "eraser"):
            self._begin_stroke(self._to_overlay_pt(pos), pressure)

    def _pointer_move(self, pos: QPointF, pressure: float):
        if self._stamp_drag_mode is not None:
            self._handle_stamp_drag(pos)
        elif self._sel_dragging:
            self._update_selection(self._sel_start, self._to_overlay_pt(pos))
        elif self.controller.tool == "stroke_eraser" and self._drawing:
            self.erase_stroke_at(self._to_overlay_pt(pos))
        elif self._drawing:
            self._continue_stroke(self._to_overlay_pt(pos), pressure)

    def _pointer_up(self, pos: QPointF):
        if self._stamp_drag_mode is not None:
            self._stamp_drag_mode = None
            self._stamp_drag_anchor = None
            self._stamp_orig_rect = None
        if self._sel_dragging:
            self._sel_dragging = False
            if self.selection is not None:
                self.controller.statusBar().showMessage("已选中文字，按 Ctrl+C 复制", 3000)
        if self._drawing:
            self._end_stroke()

    def _hover_move(self, pos: QPointF):
        if self.controller.tool == "select":
            idx = self._char_index_at(self._to_overlay_pt(pos))
            self.setCursor(Qt.IBeamCursor if idx is not None else Qt.ArrowCursor)

    def _do_pan(self, global_pos: QPointF):
        if self._pan_last_global is None:
            self._pan_last_global = global_pos
            return
        delta = global_pos - self._pan_last_global
        self._pan_last_global = global_pos
        scroll_area = self.controller.scroll_area
        h = scroll_area.horizontalScrollBar()
        v = scroll_area.verticalScrollBar()
        h.setValue(int(h.value() - delta.x()))
        v.setValue(int(v.value() - delta.y()))

    def _handle_stamp_press(self, widget_pos: QPointF):
        pos = self._to_overlay_pt(widget_pos)
        rect = self.pending_stamp["rect"]
        handle = self._handle_rect(rect)
        if handle.contains(pos):
            self._stamp_drag_mode = "resize"
        elif rect.contains(pos):
            self._stamp_drag_mode = "move"
        else:
            return
        self._stamp_drag_anchor = pos
        self._stamp_orig_rect = QRectF(rect)

    def _handle_stamp_drag(self, widget_pos: QPointF):
        pos = self._to_overlay_pt(widget_pos)
        dx = pos.x() - self._stamp_drag_anchor.x()
        dy = pos.y() - self._stamp_drag_anchor.y()
        rect = QRectF(self._stamp_orig_rect)
        if self._stamp_drag_mode == "move":
            rect.moveTopLeft(QPointF(rect.left() + dx, rect.top() + dy))
        elif self._stamp_drag_mode == "resize":
            aspect = self._stamp_orig_rect.width() / max(self._stamp_orig_rect.height(), 1)
            new_w = max(30.0, self._stamp_orig_rect.width() + dx)
            new_h = new_w / aspect
            rect.setWidth(new_w)
            rect.setHeight(new_h)
        self.pending_stamp["rect"] = rect
        self._update_stamp_buttons()
        self.update()

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        if self.controller.tool == "hand":
            self._pan_dragging = True
            self._pan_last_global = event.globalPosition()
            self.setCursor(Qt.ClosedHandCursor)
            return
        self._pointer_down(event.position(), 1.0)

    def mouseMoveEvent(self, event):
        if self._pan_dragging:
            self._do_pan(event.globalPosition())
            return
        if event.buttons() & Qt.LeftButton:
            self._pointer_move(event.position(), 1.0)
        else:
            self._hover_move(event.position())

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        if self._pan_dragging:
            self._pan_dragging = False
            self._pan_last_global = None
            self.setCursor(Qt.OpenHandCursor)
            return
        self._pointer_up(event.position())

    def contextMenuEvent(self, event):
        if self.selection is None:
            return
        menu = QMenu(self)
        copy_act = menu.addAction("复制")
        copy_act.triggered.connect(self.copy_selection)
        menu.exec(event.globalPos())

    def tabletEvent(self, event):
        etype = event.type()
        pos = event.position()
        pressure = event.pressure() if event.pressure() > 0 else 1.0
        if etype == QEvent.TabletPress:
            self._pointer_down(pos, pressure)
        elif etype == QEvent.TabletMove:
            self._pointer_move(pos, pressure)
        elif etype == QEvent.TabletRelease:
            self._pointer_up(pos)
        event.accept()
