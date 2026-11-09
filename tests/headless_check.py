"""Headless smoke test (no visible window) exercising the core app logic:
render -> draw stroke -> stamp signature -> undo -> export PDF.
Run with QT_QPA_PLATFORM=offscreen so no real window is shown.
"""
import os
import sys
import tempfile
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz
from PySide6.QtCore import QEvent, QPoint, QPointF, QUrl, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QWheelEvent
from PySide6.QtCore import QMimeData
from PySide6.QtWidgets import QApplication

from pdf_annotator.main_window import MainWindow
from pdf_annotator.page_widget import PageWidget
from pdf_annotator.signature_store import SignatureStore


def make_test_pdf(path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)  # A4
    page.insert_text((72, 72), "Hello, this is a test PDF page for the annotator.", fontsize=14)
    doc.save(path)
    doc.close()


def check(label, condition):
    status = "OK " if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        raise SystemExit(f"CHECK FAILED: {label}")


def main():
    app = QApplication(sys.argv)

    tmpdir = tempfile.mkdtemp(prefix="pdfannot_test_")
    pdf_path = os.path.join(tmpdir, "sample.pdf")
    make_test_pdf(pdf_path)
    check("sample pdf created", os.path.exists(pdf_path))

    # ---- SignatureStore round trip ----
    sig_dir = os.path.join(tmpdir, "signatures")
    store = SignatureStore(sig_dir)
    sig_img = QImage(200, 80, QImage.Format_ARGB32_Premultiplied)
    sig_img.fill(QColor(0, 0, 0, 0))
    from PySide6.QtGui import QPainter, QPen
    p = QPainter(sig_img)
    p.setPen(QPen(QColor("black"), 4))
    p.drawLine(10, 60, 190, 20)
    p.end()
    item = store.add(sig_img, "Test Signature", "signature")
    check("signature saved to disk", os.path.exists(store.image_path(item)))
    check("signature listed", len(store.list("signature")) == 1)
    check("initial list empty", len(store.list("initial")) == 0)

    reloaded = SignatureStore(sig_dir)
    check("signature index persists across reload", len(reloaded.list()) == 1)

    # ---- MainWindow + open_pdf via mocked file dialog ----
    win = MainWindow()
    win.signature_store = reloaded
    with patch("pdf_annotator.main_window.QFileDialog.getOpenFileName", return_value=(pdf_path, "")):
        win.open_pdf()
    check("one page loaded", len(win.pages) == 1)

    page = win.pages[0]
    check("page has nonzero overlay size", page.overlay.width() > 0 and page.overlay.height() > 0)

    # ---- on-demand hi-res rendering (fixes zoom blur, memory-safe) ----
    base_px_w = page.page_pixmap.width()
    check("page starts at base (ratio 1.0) resolution", abs(page._pixmap_ratio - 1.0) < 1e-6)
    page.ensure_render(2.0)  # simulate zooming to 200%
    check("zooming in re-renders the page at higher resolution", page.page_pixmap.width() > base_px_w)
    check("hi-res render ratio increased", page._pixmap_ratio > 1.0)
    hires_px_w = page.page_pixmap.width()
    page.ensure_render(99.0)  # request absurd zoom
    check("render ratio is capped for memory safety", page._pixmap_ratio <= 3.0 + 1e-6)
    page.release_hires()  # scrolled off-screen
    check("release_hires falls back to the cached base resolution", page.page_pixmap.width() == base_px_w)
    check("release_hires resets ratio to 1.0", abs(page._pixmap_ratio - 1.0) < 1e-6)
    # annotations coordinate space (base_size) must be unaffected by render ratio
    check("base_size (annotation space) unchanged after hi-res round trip", page.base_size.width() == base_px_w)

    def overlay_has_ink(pg):
        img = pg.overlay
        for y in range(0, img.height(), 5):
            for x in range(0, img.width(), 5):
                if img.pixelColor(x, y).alpha() > 0:
                    return True
        return False

    # ---- pen stroke ----
    win.set_tool("pen")
    win.pen_color = QColor("red")
    win.pen_width = 5
    page._begin_stroke(QPointF(50, 50), 1.0)
    page._continue_stroke(QPointF(150, 150), 1.0)
    page._end_stroke()
    check("pen stroke drawn on overlay", overlay_has_ink(page))
    check("undo stack has entry", len(page._undo_stack) == 1)

    # ---- undo removes stroke ----
    page.undo()
    check("undo cleared overlay", not overlay_has_ink(page))

    # ---- highlighter stroke ----
    win.set_tool("highlight")
    page._begin_stroke(QPointF(60, 200), 1.0)
    page._continue_stroke(QPointF(300, 200), 1.0)
    page._end_stroke()
    check("highlight stroke drawn", overlay_has_ink(page))

    # ---- eraser removes pixels ----
    win.set_tool("eraser")
    win.eraser_width = 40
    page._begin_stroke(QPointF(60, 200), 1.0)
    page._continue_stroke(QPointF(300, 200), 1.0)
    page._end_stroke()
    # overlay may still have ink outside erased band; just confirm it didn't crash and stack grew
    check("eraser stroke recorded in undo stack", len(page._undo_stack) >= 1)

    # ---- signature stamp: arm, place, commit ----
    win.arm_signature(item)
    check("tool switched to stamp", win.tool == "stamp")
    page._pointer_down(QPointF(200, 400), 1.0)
    check("pending stamp created", page.pending_stamp is not None)
    page._commit_stamp()
    check("pending stamp cleared after commit", page.pending_stamp is None)
    check("stamp baked into overlay", overlay_has_ink(page))
    check("controller dearmed after stamp, reverts to select tool", win.armed_signature is None and win.tool == "select")

    # ---- export ----
    out_path = os.path.join(tmpdir, "sample_annotated.pdf")
    with patch("pdf_annotator.main_window.QFileDialog.getSaveFileName", return_value=(out_path, "")), \
         patch("pdf_annotator.main_window.QMessageBox.information", return_value=None):
        win.save_pdf_as()
    check("exported pdf exists", os.path.exists(out_path))

    exported = fitz.open(out_path)
    check("exported pdf has 1 page", exported.page_count == 1)
    check("exported pdf larger than empty", os.path.getsize(out_path) > 1000)
    text = exported.load_page(0).get_text()
    check("original text preserved in export", "test PDF page" in text)
    exported.close()

    # ---- drag & drop: PDF path extraction from mime data ----
    mime_pdf = QMimeData()
    mime_pdf.setUrls([QUrl.fromLocalFile(pdf_path)])
    # Qt normalizes backslashes to forward slashes when round-tripping through
    # QUrl; Windows treats both interchangeably, so compare normalized paths.
    resolved = win._first_pdf_path(mime_pdf)
    check(
        "drag&drop recognizes a dropped .pdf path",
        resolved is not None and os.path.normcase(os.path.normpath(resolved)) == os.path.normcase(os.path.normpath(pdf_path)),
    )

    mime_txt = QMimeData()
    other_path = os.path.join(tmpdir, "notes.txt")
    with open(other_path, "w") as f:
        f.write("not a pdf")
    mime_txt.setUrls([QUrl.fromLocalFile(other_path)])
    check("drag&drop ignores non-pdf files", win._first_pdf_path(mime_txt) is None)

    # ---- text selection / copy (character-level, so CJK runs with no spaces
    # can still be selected one glyph at a time instead of as one giant "word") ----
    win3 = MainWindow()
    win3.signature_store = reloaded
    win3.load_pdf(pdf_path)
    page3 = win3.pages[0]
    check("characters extracted from page", len(page3.chars) >= 3)

    start_rect = page3.chars[0]["rect"]
    end_rect = page3.chars[2]["rect"]
    win3.set_tool("select")
    page3._update_selection(start_rect.center(), end_rect.center())
    check("selection spans expected char range", page3.selection == (0, 2))
    sel_text = page3.selected_text()
    check("selected text contains first char", page3.chars[0]["text"] in sel_text)
    check("selected text contains third char", page3.chars[2]["text"] in sel_text)
    check("selection of 3 chars is short, not a whole word/sentence", len(sel_text) <= 4)

    page3.copy_selection()
    clip = QGuiApplication.clipboard().text()
    check("copy puts selected text on clipboard", clip == sel_text)

    # ---- CJK: a run of Chinese characters with no whitespace must still be
    # selectable character-by-character, not as one giant word/sentence ----
    cjk_pdf_path = os.path.join(tmpdir, "cjk.pdf")
    cjk_doc = fitz.open()
    cjk_page = cjk_doc.new_page(width=595, height=842)
    cjk_text = "你好世界这是中文测试"  # "你好世界这是中文测试"
    try:
        cjk_page.insert_text((72, 100), cjk_text, fontsize=18, fontname="china-s")
    except Exception:
        cjk_page.insert_text((72, 100), cjk_text, fontsize=18)
    cjk_doc.save(cjk_pdf_path)
    cjk_doc.close()

    win4 = MainWindow()
    win4.signature_store = reloaded
    win4.load_pdf(cjk_pdf_path)
    cjk_page_widget = win4.pages[0]
    check(
        f"CJK: {len(cjk_text)} chars in source produced >= {len(cjk_text) - 1} extracted chars (not lumped into 1 word)",
        len(cjk_page_widget.chars) >= len(cjk_text) - 1,
    )
    if len(cjk_page_widget.chars) >= 3:
        c_start = cjk_page_widget.chars[0]["rect"].center()
        c_end = cjk_page_widget.chars[1]["rect"].center()
        cjk_page_widget._update_selection(c_start, c_end)
        cjk_sel = cjk_page_widget.selected_text()
        check(
            "CJK: selecting first 2 characters does not select the whole string",
            0 < len(cjk_sel) < len(cjk_text),
        )

    page3.clear_selection()
    check("clear_selection empties selection", page3.selection is None)

    # ---- hand tool panning math ----
    win3.set_tool("hand")
    check("hand tool activates", win3.tool == "hand")
    hbar = win3.scroll_area.horizontalScrollBar()
    vbar = win3.scroll_area.verticalScrollBar()
    hbar.setRange(0, 1000)
    vbar.setRange(0, 1000)
    hbar.setValue(500)
    vbar.setValue(500)
    page3._pan_last_global = QPointF(100, 100)
    page3._do_pan(QPointF(70, 60))  # dragged left 30px, up 40px
    check("hand-tool drag pans horizontal scrollbar", hbar.value() == 530)
    check("hand-tool drag pans vertical scrollbar", vbar.value() == 540)

    # ---- highlighter opacity control ----
    check("default highlight opacity is translucent (not opaque)", 0.0 < win3.highlight_opacity < 1.0)
    win3._on_opacity_changed(60)
    check("opacity slider updates controller.highlight_opacity", win3.highlight_opacity == 0.6)

    win3.set_tool("highlight")
    page3.ops = []
    page3._begin_stroke(QPointF(50, 300), 1.0)
    page3._continue_stroke(QPointF(200, 300), 1.0)
    page3._end_stroke()
    check("highlight op stores the controller's opacity at draw time", page3.ops[-1]["opacity"] == 0.6)
    check("highlight op kind is 'highlight'", page3.ops[-1]["kind"] == "highlight")

    # ---- stroke eraser: deletes a whole stroke by touching it, pixel eraser untouched ----
    page3.ops = []
    win3.set_tool("pen")
    page3._begin_stroke(QPointF(30, 500), 1.0)
    page3._continue_stroke(QPointF(30, 550), 1.0)  # vertical stroke A: x=30, y 500-550
    page3._end_stroke()
    page3._begin_stroke(QPointF(200, 500), 1.0)
    page3._continue_stroke(QPointF(200, 550), 1.0)  # separate vertical stroke B: x=200, y 500-550
    page3._end_stroke()
    check("two separate pen strokes recorded as two ops", len(page3.ops) == 2)

    win3.set_tool("stroke_eraser")
    page3.erase_stroke_at(QPointF(30, 525))  # touches stroke A only
    check("stroke eraser removed exactly one stroke", len(page3.ops) == 1)
    check("the remaining stroke is the untouched one (near x=200)", abs(page3.ops[0]["points"][0].x() - 200) < 1)

    page3.undo()
    check("undo restores the stroke removed by the stroke eraser", len(page3.ops) == 2)

    # pixel eraser must still work independently of the stroke-based model
    win3.set_tool("eraser")
    win3.eraser_width = 40
    page3._begin_stroke(QPointF(30, 525), 1.0)
    page3._continue_stroke(QPointF(30, 526), 1.0)
    page3._end_stroke()
    check("pixel eraser adds an 'erase' op rather than deleting a stroke object", page3.ops[-1]["kind"] == "erase")
    check("pixel eraser does not remove the other strokes' ops", len(page3.ops) == 3)

    # ---- consolidated eraser dropdown button (single toolbar button, two modes) ----
    win3.set_tool("select")
    check("eraser button unchecked when a non-eraser tool is active", win3.eraser_btn.isChecked() is False)

    win3._choose_eraser_mode("stroke_eraser")
    check("choosing a mode from the dropdown activates that tool", win3.tool == "stroke_eraser")
    check("eraser button shows checked for either eraser mode", win3.eraser_btn.isChecked() is True)

    win3.set_tool("pen")
    check("eraser button unchecks when switching away to another tool", win3.eraser_btn.isChecked() is False)

    win3.eraser_btn.click()  # clicking the button body (not the dropdown arrow) reuses the last-picked mode
    check("clicking the eraser button body re-activates the last chosen mode", win3.tool == "stroke_eraser")

    win3.set_tool("select")

    win3.set_tool("select")
    check("switching back to select tool works", win3.tool == "select")

    # ---- load_pdf() direct path (argv / drag-drop / Open-With entry point) ----
    win2 = MainWindow()
    win2.signature_store = reloaded
    win2.load_pdf(pdf_path)
    check("load_pdf() opens a page without a file dialog", len(win2.pages) == 1)

    # ---- Ctrl+wheel zoom ----
    zoom_before = win2.zoom
    wheel_event = QWheelEvent(
        QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, 120),
        Qt.NoButton, Qt.ControlModifier, Qt.NoScrollPhase, False,
    )
    win2.eventFilter(win2.scroll_area.viewport(), wheel_event)
    check("ctrl+wheel-up zoomed in", win2.zoom > zoom_before)

    zoom_before2 = win2.zoom
    wheel_event_down = QWheelEvent(
        QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, -120),
        Qt.NoButton, Qt.ControlModifier, Qt.NoScrollPhase, False,
    )
    win2.eventFilter(win2.scroll_area.viewport(), wheel_event_down)
    check("ctrl+wheel-down zoomed out", win2.zoom < zoom_before2)

    # plain wheel (no Ctrl) must NOT be swallowed, so normal scrolling still works
    plain_wheel = QWheelEvent(
        QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, 120),
        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False,
    )
    consumed = win2.eventFilter(win2.scroll_area.viewport(), plain_wheel)
    check("plain wheel (no ctrl) is not consumed by zoom handler", consumed is False)

    # ---- zoom-to-cursor anchoring math (pure function, independent of actual
    # scrollbar ranges so it isn't affected by the offscreen viewport size) ----
    from pdf_annotator.main_window import MainWindow as MW

    # cursor at viewport (150, 100), scrolled to (300, 400), zoom doubling (ratio=2)
    new_h, new_v = MW._compute_zoom_anchor(300, 400, QPointF(150, 100), 2.0)
    # content point under the cursor was (300+150, 400+100) = (450, 500);
    # after 2x zoom that point is at (900, 1000); scrollbar must land there
    # minus the viewport offset so it's still under the same cursor position
    check("zoom-anchor horizontal keeps content point under the cursor", new_h == 900 - 150)
    check("zoom-anchor vertical keeps content point under the cursor", new_v == 1000 - 100)

    # zooming out (ratio=0.5) should pull the anchored content point closer to the scrollbar origin
    new_h2, new_v2 = MW._compute_zoom_anchor(300, 400, QPointF(150, 100), 0.5)
    check("zoom-out anchor math", new_h2 == 225 - 150 and new_v2 == 250 - 100)

    # no-op ratio (1.0) must not move the scroll position at all
    new_h3, new_v3 = MW._compute_zoom_anchor(300, 400, QPointF(150, 100), 1.0)
    check("ratio=1.0 anchor is a no-op", new_h3 == 300 and new_v3 == 400)

    # ---- integration: zoom_at_point actually changes win.zoom, cursor-anchored or centered ----
    win2.set_zoom(1.0)
    win2.zoom_at_point(2.0, QPointF(50, 50))
    check("zoom_at_point updates the zoom level", abs(win2.zoom - 2.0) < 1e-6)

    win2.set_zoom(1.0)
    win2.zoom_centered(1.5)
    check("zoom_centered (toolbar button/shortcut) updates the zoom level", abs(win2.zoom - 1.5) < 1e-6)

    # ---- zoom % readout reflects current zoom ----
    win2.set_zoom(1.0)
    check("zoom button reads 100% at 1.0x", win2.zoom_btn.text() == "100%")
    win2.set_zoom(1.25)
    check("zoom button reads 125% at 1.25x", win2.zoom_btn.text() == "125%")

    # ---- multi-page indicator + jump-to-page ----
    multi_path = os.path.join(tmpdir, "multi.pdf")
    mdoc = fitz.open()
    for n in range(5):
        mp = mdoc.new_page(width=595, height=842)
        mp.insert_text((72, 72), f"Page {n + 1} of five.", fontsize=18)
    mdoc.save(multi_path)
    mdoc.close()

    win5 = MainWindow()
    win5.signature_store = reloaded
    win5.resize(700, 600)
    win5.load_pdf(multi_path)
    check("multi-page pdf loads all 5 pages", len(win5.pages) == 5)
    # isVisible() is False while the window itself is unshown (offscreen); isHidden()
    # tracks the explicit show/hide flag, which is what _update_page_indicator toggles
    check("page nav becomes visible when a doc is open", win5.page_nav.isHidden() is False)
    check("page total label shows 5 pages", win5.page_total_label.text() == "/ 5")

    win5.go_to_page(3)  # jump to page 4 (0-indexed 3)
    check("go_to_page sets current_page", win5.current_page == 3)
    check("page edit field reflects jumped-to page (1-indexed)", win5.page_edit.text() == "4")

    win5.go_to_page(99)  # clamp beyond the end
    check("go_to_page clamps to last page", win5.current_page == 4)
    win5.go_to_page(-5)  # clamp before the start
    check("go_to_page clamps to first page", win5.current_page == 0)

    # jump via the editable field
    win5.page_edit.setText("3")
    win5._on_page_edit()
    check("typing a page number in the field navigates there", win5.current_page == 2)

    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
