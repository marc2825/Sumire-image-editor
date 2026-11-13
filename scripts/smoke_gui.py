"""Reproducible real-window smoke test with synthetic images and a screenshot."""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, PngImagePlugin
from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from sumire.window import Window


def sample(path: Path, accent: str):
    image = Image.new("RGB", (1440, 1080), "#e5e0d8")
    draw = ImageDraw.Draw(image)
    draw.rectangle((65, 65, 1375, 1015), fill="#f6f1e7")
    draw.ellipse((180, 120, 1260, 1200), fill=accent)
    draw.rectangle((180, 690, 1260, 1015), fill="#334c4e")
    draw.ellipse((470, 270, 970, 770), fill="#e9bd99")
    draw.pieslice((450, 215, 990, 755), 180, 360, fill="#313e43")
    draw.rounded_rectangle((270, 755, 1170, 925), radius=16, fill="#f6f1e7")
    for x in range(320, 1110, 8):
        draw.rectangle((x, 790, x + 3, 890), fill="#36424d")
    draw.text((95, 90), "SUMIRE / LOCAL IMAGE FINISHING", fill="#334c4e", font_size=25)
    draw.text((95, 960), "SYNTHETIC TEST IMAGE  /  1440 x 1080", fill="#334c4e", font_size=20)
    info = PngImagePlugin.PngInfo()
    info.add_text("parameters", "synthetic private generation parameters")
    image.save(path, pnginfo=info)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", type=Path, default=Path("test-artifacts"))
    parser.add_argument("--font", type=Path)
    args = parser.parse_args()
    args.artifacts.mkdir(parents=True, exist_ok=True)
    inputs = args.artifacts / "smoke-input"
    inputs.mkdir(exist_ok=True)
    for number, accent in enumerate(["#87aaa0", "#a5a0b6", "#bca681"], 1):
        sample(inputs / f"illustration_{number:02}.png", accent)
    app = QApplication([])
    app.setStyle("Fusion")
    if args.font:
        QFontDatabase.addApplicationFont(str(args.font))
    window = Window()
    window.show()
    window.activateWindow()
    window.open_inputs([str(inputs)])
    stage = 0
    failure = []

    def tick():
        nonlocal stage
        try:
            if not window.document or not window.canvas.ready or window.busy() or window.saving:
                return
            document = window.document
            if stage == 0:
                window.brush.setValue(140)
                window.strength.setValue(26)
                stage = 1
            elif stage == 1 and window.canvas.ready:
                canvas = window.canvas
                canvas.setFocus()
                def pos(x, y):
                    return (QPointF(x, y) * canvas.scale + canvas.offset).toPoint()
                QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=pos(335, 840))
                QTest.mouseMove(canvas, pos(1090, 840))
                QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=pos(1090, 840))
                stage = 2
            elif stage == 2 and document.saved_revision == document.revision:
                assert document.revision == 1
                QTest.keyClick(window.canvas, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
                stage = 3
            elif stage == 3 and document.saved_revision == document.revision:
                assert document.revision == 0
                assert document.image.tobytes() == document.original.tobytes()
                QTest.keyClick(window.canvas, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
                stage = 4
            elif stage == 4 and document.saved_revision == document.revision:
                assert document.revision == 1
                with Image.open(document.output) as output:
                    assert not output.info
                    assert output.size == (1440, 1080)
                    assert output.convert("RGBA").tobytes() == document.image.tobytes()
                window.grab().save(str(args.artifacts / "sumire-preview.png"))
                print("PASS: GUI launch, brush, autosave, Ctrl+Z, redo, export and screenshot")
                timer.stop()
                window.close()
                app.quit()
        except Exception as error:
            failure.append(type(error).__name__)
            timer.stop()
            document.saved_revision = document.revision
            window.auto.setChecked(False)
            window.close()
            app.quit()

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(100)
    QTimer.singleShot(30000, lambda: (failure.append("Timeout"), app.quit()))
    app.exec()
    if failure:
        raise SystemExit(f"FAIL: {failure}")


if __name__ == "__main__":
    main()
