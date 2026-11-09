import os

import fitz  # PyMuPDF
from PySide6.QtCore import QEvent, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QStatusBar,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from . import icons
from .page_widget import PageWidget
from .signature_dialog import SignatureDialog
from .signature_store import SignatureStore

PEN_PRESETS = [("黑色", "#111111"), ("红色", "#e53935"), ("蓝色", "#1e88e5"), ("绿色", "#2e7d32")]
HILITE_PRESETS = [("黄色", "#ffeb3b"), ("绿色", "#69f0ae"), ("粉色", "#ff80ab"), ("蓝色", "#40c4ff")]

TOOLBAR_QSS = """
QToolBar {
    background: #F3F4F6;
    border: none;
    border-bottom: 1px solid #D7D9DC;
    spacing: 2px;
    padding: 4px 6px;
}
QToolButton {
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 5px;
}
QToolButton:hover {
    background: #E5E7EB;
}
QToolButton:checked {
    background: #D2E3FC;
}
QToolButton:pressed {
    background: #CBD5E1;
}
"""


def _swatch_icon(color: QColor, size=18) -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    from PySide6.QtGui import QPainter, QPen

    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(color)
    painter.setPen(QPen(QColor("#555"), 1))
    painter.drawEllipse(1, 1, size - 2, size - 2)
    painter.end()
    return QIcon(pix)


def _draw_eraser_block(painter, cx, cy, w, h, angle):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QPen

    painter.save()
    painter.translate(cx, cy)
    painter.rotate(angle)
    rect = QRectF(-w / 2, -h / 2, w, h)

    painter.setPen(QPen(icons.INK, 1.4))
    painter.setBrush(QColor("#FFF3E0"))
    painter.drawRoundedRect(rect, 3, 3)

    painter.save()
    painter.setClipRect(QRectF(-w / 2, -h / 2, w, h * 0.55))
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#F06292"))
    painter.drawRoundedRect(rect, 3, 3)
    painter.restore()

    painter.setPen(QPen(icons.INK, 1.4))
    painter.setBrush(Qt.NoBrush)
    painter.drawRoundedRect(rect, 3, 3)
    painter.restore()


def _eraser_icon(mode: str, size=36) -> QIcon:
    """mode: 'eraser' (pixel) draws a plain eraser block;
    'stroke_eraser' draws a squiggly stroke fading out under an eraser,
    to visually distinguish "erase pixels" from "erase the whole stroke"."""
    import math

    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPainter, QPen

    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)

    if mode == "stroke_eraser":
        pts = [QPointF(4 + i * (22 / 12), size * 0.55 + math.sin(i * 0.9) * size * 0.14) for i in range(13)]
        pen = QPen(QColor("#42A5F5"), 3)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        for a, b in zip(pts[:8], pts[1:9]):
            painter.drawLine(a, b)
        fade_pen = QPen(QColor(66, 165, 245, 70), 3)
        fade_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(fade_pen)
        for a, b in zip(pts[7:], pts[8:]):
            painter.drawLine(a, b)
        _draw_eraser_block(painter, size * 0.74, size * 0.32, size * 0.4, size * 0.27, -20)
    else:
        _draw_eraser_block(painter, size * 0.5, size * 0.5, size * 0.56, size * 0.38, -18)

    painter.end()
    return QIcon(pix)


class SignatureManagerDialog(QDialog):
    def __init__(self, parent, store: SignatureStore):
        super().__init__(parent)
        self.setWindowTitle("管理签名")
        self.store = store
        layout = QVBoxLayout(self)
        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)
        self._reload()

        btn_row = QHBoxLayout()
        del_btn = QPushButton("删除选中")
        del_btn.clicked.connect(self._delete_selected)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(del_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _reload(self):
        self.list_widget.clear()
        for item in self.store.list():
            label = f"{'签名' if item['type'] == 'signature' else 'Initial'} · {item['name']}"
            list_item = QListWidgetItem(label)
            list_item.setData(Qt.UserRole, item["id"])
            self.list_widget.addItem(list_item)

    def _delete_selected(self):
        item = self.list_widget.currentItem()
        if item is None:
            return
        self.store.delete(item.data(Qt.UserRole))
        self._reload()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("墨签 InkSign")
        self.resize(1100, 850)

        self.doc = None
        self.doc_path = None
        self.original_bytes = None
        self.pages = []
        self.active_page = None
        self.active_stamp_page = None

        self.tool = "select"
        self.pen_color = QColor("#111111")
        self.pen_width = 3
        self.highlight_color = QColor("#ffeb3b")
        self.highlight_width = 18
        self.highlight_opacity = 0.4
        self.eraser_width = 24
        self.armed_signature = None
        self.zoom = 1.0

        self.signature_store = SignatureStore()

        self._build_ui()
        self.setStatusBar(QStatusBar())
        self._build_page_nav()
        self.statusBar().showMessage("请打开一个 PDF 文件")

    def _build_page_nav(self):
        """Persistent page indicator + jump field on the right of the status bar."""
        self.page_nav = QWidget()
        lay = QHBoxLayout(self.page_nav)
        lay.setContentsMargins(4, 0, 8, 0)
        lay.setSpacing(4)

        self.prev_page_btn = QToolButton()
        self.prev_page_btn.setText("‹")
        self.prev_page_btn.setToolTip("上一页")
        self.prev_page_btn.clicked.connect(lambda: self.go_to_page(self.current_page - 1))

        self.page_edit = QLineEdit()
        self.page_edit.setFixedWidth(40)
        self.page_edit.setAlignment(Qt.AlignCenter)
        self.page_edit.returnPressed.connect(self._on_page_edit)

        self.page_total_label = QLabel("/ 0")

        self.next_page_btn = QToolButton()
        self.next_page_btn.setText("›")
        self.next_page_btn.setToolTip("下一页")
        self.next_page_btn.clicked.connect(lambda: self.go_to_page(self.current_page + 1))

        lay.addWidget(self.prev_page_btn)
        lay.addWidget(self.page_edit)
        lay.addWidget(self.page_total_label)
        lay.addWidget(self.next_page_btn)
        self.statusBar().addPermanentWidget(self.page_nav)

        self.current_page = 0
        self.page_nav.setVisible(False)

    # ---------------------------------------------------------------- UI
    def _build_ui(self):
        self.setAcceptDrops(True)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setAlignment(Qt.AlignHCenter)
        scroll.viewport().installEventFilter(self)
        scroll.verticalScrollBar().valueChanged.connect(self._on_scrolled)
        self.scroll_area = scroll

        # debounce hi-res re-rendering of visible pages after zoom/scroll settles
        self._hires_timer = QTimer(self)
        self._hires_timer.setSingleShot(True)
        self._hires_timer.setInterval(130)
        self._hires_timer.timeout.connect(self._refresh_visible_resolution)

        container = QWidget()
        container.setObjectName("pageCanvas")
        container.setStyleSheet("#pageCanvas { background: #6B6E72; }")
        # outer layout centers the pages column horizontally within the gray canvas
        outer = QHBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        pages_holder = QWidget()
        pages_holder.setStyleSheet("background: transparent;")
        self.pages_layout = QVBoxLayout(pages_holder)
        self.pages_layout.setSpacing(20)
        self.pages_layout.setContentsMargins(24, 24, 24, 24)
        self.pages_layout.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        outer.addWidget(pages_holder)
        outer.addStretch(1)
        scroll.setWidget(container)
        self.setCentralWidget(scroll)

        toolbar = QToolBar("工具栏")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(22, 22))
        toolbar.setToolButtonStyle(Qt.ToolButtonIconOnly)
        toolbar.setStyleSheet(TOOLBAR_QSS)
        self.addToolBar(toolbar)

        open_act = QAction(icons.icon_open(), "打开 PDF", self)
        open_act.setShortcut(QKeySequence.Open)
        open_act.triggered.connect(self.open_pdf)
        toolbar.addAction(open_act)

        save_act = QAction(icons.icon_save(), "另存为...", self)
        save_act.setShortcut(QKeySequence.Save)
        save_act.triggered.connect(self.save_pdf_as)
        toolbar.addAction(save_act)

        toolbar.addSeparator()

        self.tool_actions = {}
        self.tool_group = QActionGroup(self)
        self.tool_group.setExclusive(True)

        def add_tool_action(icon, label, name, shortcut=None):
            act = QAction(icon, label, self, checkable=True)
            if shortcut:
                act.setShortcut(shortcut)
            act.triggered.connect(lambda checked=False, n=name: self.set_tool(n))
            toolbar.addAction(act)
            self.tool_group.addAction(act)
            self.tool_actions[name] = act
            return act

        self.act_select = add_tool_action(icons.icon_select(), "选择文本 (V)", "select", "V")
        self.act_select.setChecked(True)
        self.act_hand = add_tool_action(icons.icon_hand(), "抓手 (H)", "hand", "H")

        toolbar.addSeparator()

        self.act_pen = add_tool_action(icons.icon_pen(), "画笔", "pen")
        self.act_highlight = add_tool_action(icons.icon_highlighter(), "荧光笔", "highlight")

        self._eraser_mode = "eraser"
        self.eraser_btn = QToolButton()
        self.eraser_btn.setCheckable(True)
        self.eraser_btn.setPopupMode(QToolButton.MenuButtonPopup)
        self.eraser_btn.setIcon(_eraser_icon("eraser"))
        self.eraser_btn.setToolTip("橡皮擦（像素）")
        self.eraser_btn.clicked.connect(lambda: self.set_tool(self._eraser_mode))

        eraser_menu = QMenu(self.eraser_btn)
        eraser_mode_group = QActionGroup(self.eraser_btn)
        eraser_mode_group.setExclusive(True)

        act_pixel_eraser = eraser_menu.addAction(_eraser_icon("eraser"), "像素橡皮擦")
        act_pixel_eraser.setCheckable(True)
        act_pixel_eraser.setChecked(True)
        act_pixel_eraser.triggered.connect(lambda: self._choose_eraser_mode("eraser"))
        eraser_mode_group.addAction(act_pixel_eraser)

        act_stroke_eraser = eraser_menu.addAction(_eraser_icon("stroke_eraser"), "整笔橡皮擦")
        act_stroke_eraser.setCheckable(True)
        act_stroke_eraser.triggered.connect(lambda: self._choose_eraser_mode("stroke_eraser"))
        eraser_mode_group.addAction(act_stroke_eraser)

        self.eraser_btn.setMenu(eraser_menu)
        toolbar.addWidget(self.eraser_btn)

        toolbar.addSeparator()

        self.pen_color_btn = self._make_color_button(PEN_PRESETS, self._set_pen_color, self.pen_color)
        self.pen_color_btn.setToolTip("画笔颜色")
        toolbar.addWidget(self.pen_color_btn)

        self.hilite_color_btn = self._make_color_button(HILITE_PRESETS, self._set_highlight_color, self.highlight_color)
        self.hilite_color_btn.setToolTip("荧光笔颜色")
        toolbar.addWidget(self.hilite_color_btn)

        self.width_btn, self.width_slider = self._make_slider_popup(
            icons.icon_thickness_badge(), "粗细", 1, 50, self.pen_width,
            self._on_width_changed, suffix=" px",
        )
        toolbar.addWidget(self.width_btn)

        self.opacity_btn, self.opacity_slider = self._make_slider_popup(
            icons.icon_droplet_badge(), "荧光笔透明度（数值越小，底下文字越清楚）",
            10, 90, int(self.highlight_opacity * 100), self._on_opacity_changed, suffix=" %",
        )
        toolbar.addWidget(self.opacity_btn)

        toolbar.addSeparator()

        undo_act = QAction(icons.icon_undo(), "撤销", self)
        undo_act.setShortcut(QKeySequence.Undo)
        undo_act.triggered.connect(self.undo_active)
        toolbar.addAction(undo_act)

        clear_act = QAction(icons.icon_clear(), "清空本页", self)
        clear_act.triggered.connect(self.clear_active_page)
        toolbar.addAction(clear_act)

        toolbar.addSeparator()

        zoom_out_act = QAction(icons.icon_zoom_out(), "缩小", self)
        zoom_out_act.setShortcut(QKeySequence.ZoomOut)
        zoom_out_act.triggered.connect(lambda: self.zoom_centered(self.zoom / 1.15))
        toolbar.addAction(zoom_out_act)

        self.zoom_btn = QToolButton()
        self.zoom_btn.setText("100%")
        self.zoom_btn.setToolTip("缩放比例")
        self.zoom_btn.setPopupMode(QToolButton.InstantPopup)
        self.zoom_btn.setStyleSheet(
            "QToolButton{min-width:52px; font-weight:600; color:#37474F;}"
            "QToolButton::menu-indicator{width:0px;}"
        )
        zoom_menu = QMenu(self.zoom_btn)
        for label, factor in [("适合宽度", "fit"), ("50%", 0.5), ("75%", 0.75),
                              ("100%", 1.0), ("125%", 1.25), ("150%", 1.5),
                              ("200%", 2.0), ("400%", 4.0)]:
            act = zoom_menu.addAction(label)
            if factor == "fit":
                act.triggered.connect(self.zoom_fit_width)
            else:
                act.triggered.connect(lambda checked=False, f=factor: self.zoom_centered(f))
        self.zoom_btn.setMenu(zoom_menu)
        toolbar.addWidget(self.zoom_btn)

        zoom_in_act = QAction(icons.icon_zoom_in(), "放大", self)
        zoom_in_act.setShortcut(QKeySequence.ZoomIn)
        zoom_in_act.triggered.connect(lambda: self.zoom_centered(self.zoom * 1.15))
        toolbar.addAction(zoom_in_act)
        zoom_reset_act = QAction(icons.icon_zoom_reset(), "适合宽度", self)
        zoom_reset_act.setShortcut("Ctrl+0")
        zoom_reset_act.triggered.connect(self.zoom_fit_width)
        toolbar.addAction(zoom_reset_act)
        # Ctrl+scroll-wheel also zooms; see eventFilter()

        toolbar.addSeparator()

        copy_act = QAction("复制", self)
        copy_act.setShortcut(QKeySequence.Copy)
        copy_act.triggered.connect(self.copy_selection)
        self.addAction(copy_act)

        self.signature_btn = QToolButton()
        self.signature_btn.setIcon(icons.icon_signature())
        self.signature_btn.setToolTip("签名")
        self.signature_btn.setPopupMode(QToolButton.InstantPopup)
        self.signature_menu = QMenu(self.signature_btn)
        self.signature_btn.setMenu(self.signature_menu)
        toolbar.addWidget(self.signature_btn)
        self._refresh_signature_menu()

    def _icon_label(self, icon: QIcon, tooltip: str) -> QLabel:
        label = QLabel()
        label.setPixmap(icon.pixmap(18, 18))
        label.setToolTip(tooltip)
        label.setContentsMargins(6, 0, 2, 0)
        return label

    def _make_slider_popup(self, icon, title, minv, maxv, value, on_change, suffix=""):
        """A toolbar button that opens a small pop-up panel holding one slider
        with a live value readout — keeps the toolbar compact instead of
        stacking full-width sliders inline."""
        btn = QToolButton()
        btn.setIcon(icon)
        btn.setToolTip(title)
        btn.setPopupMode(QToolButton.InstantPopup)

        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        header = QHBoxLayout()
        title_label = QLabel(title.split("（")[0])
        title_label.setStyleSheet("font-weight:600;")
        value_label = QLabel(f"{value}{suffix}")
        value_label.setStyleSheet("color:#1E88E5; font-weight:600;")
        value_label.setAlignment(Qt.AlignRight)
        header.addWidget(title_label)
        header.addStretch(1)
        header.addWidget(value_label)
        lay.addLayout(header)

        slider = QSlider(Qt.Horizontal)
        slider.setRange(minv, maxv)
        slider.setValue(value)
        slider.setFixedWidth(180)

        def handle(v):
            value_label.setText(f"{v}{suffix}")
            on_change(v)

        slider.valueChanged.connect(handle)
        lay.addWidget(slider)

        menu = QMenu(btn)
        action = QWidgetAction(menu)
        action.setDefaultWidget(panel)
        menu.addAction(action)
        btn.setMenu(menu)
        # keep the readout label in sync when the slider is changed programmatically
        slider._value_label = value_label
        slider._suffix = suffix
        return btn, slider

    def _make_color_button(self, presets, setter, initial: QColor):
        btn = QToolButton()
        btn.setIcon(_swatch_icon(initial))
        btn.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(btn)
        for name, hex_code in presets:
            color = QColor(hex_code)
            act = menu.addAction(_swatch_icon(color), name)
            act.triggered.connect(lambda checked=False, c=color, b=btn: (setter(c), b.setIcon(_swatch_icon(c))))
        menu.addSeparator()
        custom_act = menu.addAction("自定义颜色...")

        def pick_custom():
            from PySide6.QtWidgets import QColorDialog

            color = QColorDialog.getColor(initial, self, "选择颜色")
            if color.isValid():
                setter(color)
                btn.setIcon(_swatch_icon(color))

        custom_act.triggered.connect(pick_custom)
        btn.setMenu(menu)
        return btn

    # ------------------------------------------------------------ signature menu
    def _refresh_signature_menu(self):
        self.signature_menu.clear()
        signatures = self.signature_store.list("signature")
        initials = self.signature_store.list("initial")

        if signatures:
            self.signature_menu.addSection("我的签名")
            for item in signatures:
                act = self.signature_menu.addAction(f"✍ {item['name']}")
                act.triggered.connect(lambda checked=False, it=item: self.arm_signature(it))
        if initials:
            self.signature_menu.addSection("我的缩写 (Initial)")
            for item in initials:
                act = self.signature_menu.addAction(f"🖊 {item['name']}")
                act.triggered.connect(lambda checked=False, it=item: self.arm_signature(it))

        self.signature_menu.addSeparator()
        new_sig = self.signature_menu.addAction("+ 新建签名...")
        new_sig.triggered.connect(lambda: self._create_signature("signature"))
        new_initial = self.signature_menu.addAction("+ 新建缩写 (Initial)...")
        new_initial.triggered.connect(lambda: self._create_signature("initial"))
        manage_act = self.signature_menu.addAction("管理签名...")
        manage_act.triggered.connect(self._open_signature_manager)

    def _create_signature(self, default_type):
        dialog = SignatureDialog(self, default_type=default_type)
        if dialog.exec() == QDialog.Accepted and dialog.result_item:
            r = dialog.result_item
            self.signature_store.add(r["image"], r["name"], r["type"])
            self._refresh_signature_menu()

    def _open_signature_manager(self):
        dialog = SignatureManagerDialog(self, self.signature_store)
        dialog.exec()
        self._refresh_signature_menu()

    def arm_signature(self, item):
        self.armed_signature = item
        self.set_tool("stamp")
        self.statusBar().showMessage(f"已选择「{item['name']}」，点击页面上的位置放置，可拖动/缩放，完成后点 ✓")

    def load_armed_signature_image(self):
        if self.armed_signature is None:
            return None
        return self.signature_store.load_image(self.armed_signature)

    def on_stamp_ended(self):
        self.active_stamp_page = None
        self.armed_signature = None
        self.set_tool("select")
        self.statusBar().showMessage("就绪")

    def set_active_stamp_page(self, page_widget):
        if self.active_stamp_page is not None and self.active_stamp_page is not page_widget:
            self.active_stamp_page.cancel_pending_stamp()
        self.active_stamp_page = page_widget

    # ------------------------------------------------------------ tool state
    TOOL_CURSORS = {
        "pen": Qt.CrossCursor,
        "highlight": Qt.CrossCursor,
        "eraser": Qt.CrossCursor,
        "stroke_eraser": Qt.CrossCursor,
        "stamp": Qt.PointingHandCursor,
        "hand": Qt.OpenHandCursor,
        "select": Qt.IBeamCursor,
    }

    def set_tool(self, tool_name):
        if self.active_stamp_page is not None and tool_name != "stamp":
            self.active_stamp_page.cancel_pending_stamp()
            self.active_stamp_page = None
        if tool_name != "stamp":
            self.armed_signature = None
        self.tool = tool_name
        checked_action = self.tool_actions.get(tool_name)
        if checked_action is not None:
            checked_action.setChecked(True)
        else:
            current = self.tool_group.checkedAction()
            if current is not None:
                current.setChecked(False)
        self.eraser_btn.setChecked(tool_name in ("eraser", "stroke_eraser"))
        if tool_name in ("eraser", "stroke_eraser"):
            self._eraser_mode = tool_name
            self.eraser_btn.setIcon(_eraser_icon(tool_name))
            self.eraser_btn.setToolTip("橡皮擦（像素）" if tool_name == "eraser" else "橡皮擦（整笔）")
        self._sync_width_slider()
        cursor = self.TOOL_CURSORS.get(tool_name, Qt.ArrowCursor)
        for page in self.pages:
            page.setCursor(cursor)

    def _choose_eraser_mode(self, mode):
        self._eraser_mode = mode
        self.set_tool(mode)

    def clear_other_page_selections(self, keep_page):
        for page in self.pages:
            if page is not keep_page:
                page.clear_selection()

    def copy_selection(self):
        if self.active_page is not None:
            self.active_page.copy_selection()

    def _sync_width_slider(self):
        value = {
            "pen": self.pen_width,
            "highlight": self.highlight_width,
            "eraser": self.eraser_width,
            "stroke_eraser": self.eraser_width,
        }.get(self.tool, self.pen_width)
        self.width_slider.blockSignals(True)
        self.width_slider.setValue(value)
        self.width_slider.blockSignals(False)
        label = getattr(self.width_slider, "_value_label", None)
        if label is not None:
            label.setText(f"{value}{getattr(self.width_slider, '_suffix', '')}")

    def _on_width_changed(self, value):
        if self.tool == "highlight":
            self.highlight_width = value
        elif self.tool in ("eraser", "stroke_eraser"):
            self.eraser_width = value
        else:
            self.pen_width = value

    def _on_opacity_changed(self, value):
        self.highlight_opacity = value / 100.0

    def _set_pen_color(self, color: QColor):
        self.pen_color = color

    def _set_highlight_color(self, color: QColor):
        self.highlight_color = color

    def set_active_page(self, page_widget):
        self.active_page = page_widget

    def undo_active(self):
        if self.active_page is not None:
            self.active_page.undo()

    def clear_active_page(self):
        if self.active_page is None:
            return
        reply = QMessageBox.question(self, "清空本页", "确定要清空当前页的所有批注吗？")
        if reply == QMessageBox.Yes:
            self.active_page.clear_page()

    ZOOM_MIN = 0.3
    ZOOM_MAX = 4.0

    def set_zoom(self, value):
        self.zoom = max(self.ZOOM_MIN, min(self.ZOOM_MAX, value))
        for page in self.pages:
            page.set_display_scale(self.zoom)
        if hasattr(self, "zoom_btn"):
            self.zoom_btn.setText(f"{round(self.zoom * 100)}%")
        if hasattr(self, "_hires_timer"):
            self._hires_timer.start()

    def _refresh_visible_resolution(self):
        """Render pages currently in the viewport at a resolution matching the
        zoom (crisp), and drop off-screen pages back to the cached low-res so
        memory stays bounded regardless of document length or zoom."""
        if not self.pages:
            return
        viewport = self.scroll_area.viewport()
        vtop, vbottom = 0, viewport.height()
        for page in self.pages:
            top = page.mapTo(viewport, page.rect().topLeft()).y()
            bottom = top + page.height()
            if bottom > vtop and top < vbottom:
                page.ensure_render(self.zoom)
            else:
                page.release_hires()

    def zoom_fit_width(self):
        """Scale so the page fills the available viewport width (Adobe's
        'fit width' default)."""
        if not self.pages:
            self.zoom_centered(1.0)
            return
        base_w = self.pages[0].base_size.width()
        if base_w <= 0:
            return
        avail = self.scroll_area.viewport().width() - 2 * 24 - 48  # canvas margins + breathing room
        target = max(self.ZOOM_MIN, min(self.ZOOM_MAX, avail / base_w))
        self.zoom_centered(target)

    @staticmethod
    def _compute_zoom_anchor(hbar_value, vbar_value, viewport_pos, ratio):
        """Pure math for zoom-to-cursor: given the current scroll position and
        the zoom ratio being applied, return the (h, v) scrollbar values that
        keep the content point under viewport_pos fixed on screen."""
        content_x = hbar_value + viewport_pos.x()
        content_y = vbar_value + viewport_pos.y()
        new_h = round(content_x * ratio - viewport_pos.x())
        new_v = round(content_y * ratio - viewport_pos.y())
        return new_h, new_v

    def zoom_at_point(self, new_zoom, viewport_pos):
        """Zoom while keeping the content point under viewport_pos fixed on
        screen — e.g. what's under the cursor stays under the cursor,
        instead of the view drifting toward the top-left corner."""
        old_zoom = self.zoom
        clamped = max(self.ZOOM_MIN, min(self.ZOOM_MAX, new_zoom))
        if clamped == old_zoom:
            return
        hbar = self.scroll_area.horizontalScrollBar()
        vbar = self.scroll_area.verticalScrollBar()
        ratio = clamped / old_zoom
        new_h, new_v = self._compute_zoom_anchor(hbar.value(), vbar.value(), viewport_pos, ratio)

        self.set_zoom(new_zoom)

        hbar.setValue(new_h)
        vbar.setValue(new_v)

    def zoom_centered(self, new_zoom):
        """Zoom in/out via toolbar button or keyboard shortcut — anchor on
        the viewport's current center since there's no cursor position."""
        center = self.scroll_area.viewport().rect().center()
        self.zoom_at_point(new_zoom, center)

    # ------------------------------------------------------------ page navigation
    def _on_scrolled(self, _value=None):
        self._update_page_indicator()
        if hasattr(self, "_hires_timer"):
            self._hires_timer.start()

    def _visible_page_index(self):
        """Index of the page whose area occupies the most of the viewport —
        i.e. the one the user is currently reading."""
        if not self.pages:
            return 0
        viewport = self.scroll_area.viewport()
        vtop = 0
        vbottom = viewport.height()
        best_i, best_overlap = 0, -1
        for i, page in enumerate(self.pages):
            top = page.mapTo(viewport, page.rect().topLeft()).y()
            bottom = top + page.height()
            overlap = min(bottom, vbottom) - max(top, vtop)
            if overlap > best_overlap:
                best_overlap, best_i = overlap, i
        return best_i

    def _refresh_page_labels(self, index):
        """Update the nav widgets to reflect a known current-page index."""
        self.current_page = index
        self.page_total_label.setText(f"/ {len(self.pages)}")
        if not self.page_edit.hasFocus():
            self.page_edit.setText(str(index + 1))
        self.prev_page_btn.setEnabled(index > 0)
        self.next_page_btn.setEnabled(index < len(self.pages) - 1)

    def _update_page_indicator(self):
        """Recompute the current page from the scroll position (called while
        the user scrolls) and refresh the indicator."""
        if not self.pages:
            self.page_nav.setVisible(False)
            return
        self.page_nav.setVisible(True)
        self._refresh_page_labels(self._visible_page_index())

    def go_to_page(self, index):
        if not self.pages:
            return
        index = max(0, min(len(self.pages) - 1, index))
        page = self.pages[index]
        viewport = self.scroll_area.viewport()
        y = page.mapTo(viewport, page.rect().topLeft()).y() + self.scroll_area.verticalScrollBar().value()
        # setValue emits valueChanged -> _on_scrolled, but the geometry may not
        # have settled yet, so trust the explicit target for the label update.
        self.scroll_area.verticalScrollBar().setValue(int(y) - 24)
        self._refresh_page_labels(index)

    def _on_page_edit(self):
        try:
            n = int(self.page_edit.text())
        except ValueError:
            self._update_page_indicator()
            return
        self.go_to_page(n - 1)
        self.scroll_area.setFocus()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            if self.active_stamp_page is not None:
                self.active_stamp_page.cancel_pending_stamp()
                self.active_stamp_page = None
            if self.active_page is not None:
                self.active_page.clear_selection()
            self.set_tool("select")
        else:
            super().keyPressEvent(event)

    # ------------------------------------------------------------ drag & drop / wheel zoom
    @staticmethod
    def _first_pdf_path(mime_data):
        if not mime_data.hasUrls():
            return None
        for url in mime_data.urls():
            path = url.toLocalFile()
            if path.lower().endswith(".pdf") and os.path.isfile(path):
                return path
        return None

    def dragEnterEvent(self, event):
        if self._first_pdf_path(event.mimeData()) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self._first_pdf_path(event.mimeData()) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        path = self._first_pdf_path(event.mimeData())
        if path is not None:
            event.acceptProposedAction()
            self.load_pdf(path)
        else:
            event.ignore()

    def eventFilter(self, obj, event):
        if obj is self.scroll_area.viewport() and event.type() == QEvent.Wheel:
            if event.modifiers() & Qt.ControlModifier:
                notches = event.angleDelta().y() / 120.0
                if notches:
                    self.zoom_at_point(self.zoom * (1.15 ** notches), event.position())
                return True
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------ document I/O
    def open_pdf(self):
        path, _ = QFileDialog.getOpenFileName(self, "打开 PDF", "", "PDF 文件 (*.pdf)")
        if not path:
            return
        self.load_pdf(path)

    def load_pdf(self, path: str):
        """Open a PDF given a filesystem path directly (drag & drop, command-line
        argument, or 'Open with' file association all funnel through here)."""
        try:
            with open(path, "rb") as f:
                data = f.read()
            doc = fitz.open(stream=data, filetype="pdf")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "打开失败", f"无法打开该 PDF：\n{exc}")
            return

        for i in reversed(range(self.pages_layout.count())):
            widget = self.pages_layout.itemAt(i).widget()
            if widget is not None:
                if hasattr(widget, "cleanup"):
                    widget.cleanup()
                widget.setParent(None)
        self.pages = []
        self.active_page = None
        self.active_stamp_page = None

        self.doc = doc
        self.doc_path = path
        self.original_bytes = data

        for i in range(doc.page_count):
            page_widget = PageWidget(doc[i], i, controller=self)
            page_widget.set_display_scale(self.zoom)
            shadow = QGraphicsDropShadowEffect(page_widget)
            shadow.setBlurRadius(24)
            shadow.setColor(QColor(0, 0, 0, 120))
            shadow.setOffset(0, 3)
            page_widget.setGraphicsEffect(shadow)
            self.pages_layout.addWidget(page_widget, 0, Qt.AlignHCenter)
            self.pages.append(page_widget)

        self.setWindowTitle(f"墨签 InkSign - {os.path.basename(path)}")
        self.statusBar().showMessage(f"已打开 {os.path.basename(path)}，共 {doc.page_count} 页")
        self.set_tool(self.tool)
        self._update_page_indicator()
        # fit the page to the window on open (deferred so the viewport geometry
        # has settled); Adobe's default framing with margins + shadow visible
        QTimer.singleShot(0, self.zoom_fit_width)

    def save_pdf_as(self):
        if self.doc is None or self.original_bytes is None:
            QMessageBox.information(self, "提示", "请先打开一个 PDF 文件。")
            return
        base = os.path.splitext(os.path.basename(self.doc_path))[0]
        default_name = os.path.join(os.path.dirname(self.doc_path), f"{base}_annotated.pdf")
        path, _ = QFileDialog.getSaveFileName(self, "另存为", default_name, "PDF 文件 (*.pdf)")
        if not path:
            return
        try:
            export_doc = fitz.open(stream=self.original_bytes, filetype="pdf")
            for page_widget in self.pages:
                png_bytes = page_widget.overlay_png_bytes()
                page = export_doc[page_widget.page_index]
                page.insert_image(page.rect, stream=png_bytes)
            export_doc.save(path)
            export_doc.close()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "保存失败", f"导出 PDF 时出错：\n{exc}")
            return
        self.statusBar().showMessage(f"已保存到 {path}")
        QMessageBox.information(self, "已保存", f"文件已保存到：\n{path}")
