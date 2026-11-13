"""Screenshots of the real app for the distribution page, using only synthetic images.

    python -m scripts.capture_screens --output dist/media

Each interface language runs in its own process (texts are made when the
interface modules load). The app is set up exactly as at a normal start
(style, bundled font, Qt's translations) but its window is never put on the
screen (Qt's offscreen rendering on Windows, or QT_QPA_PLATFORM=offscreen).
Settings and records go to a temporary profile; the user's are not touched.
The images are drawn here, so the screenshots contain nobody's pictures.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from PIL import Image, ImageDraw, PngImagePlugin

PALETTE = [("#87aaa0", "#334c4e"), ("#a5a0b6", "#3d3a52"), ("#bca681", "#4a3f2c"),
           ("#9fb4cf", "#2f3e57"), ("#c9a1a8", "#523138"), ("#a8c49a", "#33452b")]
SYNTHETIC_PROMPT = "synthetic sample prompt, violet flowers, soft light, (made for the Sumire screenshots)"


def illustration(path: Path, accent: str, ink: str, number: int):
    """A plain drawn picture with a fake signature in the corner (the part to hide)."""
    image = Image.new("RGB", (1200, 900), "#ece6dc")
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 40, 1160, 860), fill="#f7f2e8")
    draw.ellipse((150, 90, 1050, 990), fill=accent)
    draw.rectangle((150, 600, 1050, 860), fill=ink)
    draw.ellipse((420, 230, 780, 590), fill="#ecc6a6")
    draw.pieslice((400, 190, 800, 590), 180, 360, fill=ink)
    for index in range(7):
        x, y = 120 + index * 150, 120 + (index % 3) * 30
        draw.ellipse((x, y, x + 46, y + 46), fill="#8d7bb8")
        draw.ellipse((x + 15, y + 15, x + 31, y + 31), fill="#f3d36b")
    draw.rounded_rectangle((820, 770, 1130, 840), radius=10, fill="#f7f2e8")
    draw.text((840, 785), f"SAMPLE SIGN {number:02}", fill=ink, font_size=34)
    info = PngImagePlugin.PngInfo()
    info.add_text("parameters", SYNTHETIC_PROMPT)
    info.add_text("Software", "Sumire sample generator")
    exif = Image.Exif()
    exif[0x010F] = "Sample Camera"   # Make
    exif[0x0110] = "SC-1"            # Model
    exif[0x0132] = "2026:11:13 12:00:00"
    image.save(path, pnginfo=info, exif=exif.tobytes())


def prepare_images(folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    for number, (accent, ink) in enumerate(PALETTE, 1):
        illustration(folder / f"illustration_{number:02}.png", accent, ink, number)


def wait(app, condition, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    raise TimeoutError("the window did not become ready")


def settle(app, seconds=0.4):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


def animate(app, page, output: Path):
    """A short loop of the real window: open the next image, hide its signature, saved."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtTest import QTest
    page.navigate(1)
    wait(app, lambda: page.document is not None and page.canvas.ready and not page.busy())
    settle(app, 0.4)
    canvas = page.canvas

    def at(x, y):
        shown = QPointF(x * canvas.image.width() / 1200, y * canvas.image.height() / 900)
        return (shown * canvas.scale + canvas.offset).toPoint()

    def frame(repeat=1):
        image = page.window().grab().toImage()
        # Keep the converted image alive while its pixels are copied.
        converted = image.convertToFormat(image.Format.Format_RGBA8888)
        picture = Image.frombytes("RGBA", (converted.width(), converted.height()), bytes(converted.constBits()),
                                  "raw", "RGBA", converted.bytesPerLine())
        picture = picture.convert("RGB").resize((960, round(960 * image.height() / image.width())), Image.Resampling.LANCZOS)
        frames.extend([picture] * repeat)
    frames = []
    frame(6)
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=at(850, 805))
    for x in range(850, 1121, 18):
        QTest.mouseMove(canvas, at(x, 805))
        settle(app, 0.05)
        frame()
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=at(1120, 805))
    wait(app, lambda: page.document.revision > 0 and page.document.saved_revision == page.document.revision
         and not page.saving, 60)
    settle(app, 0.4)
    frame(12)
    frames[0].save(output / "demo-mosaic-ja.gif", save_all=True, append_images=frames[1:], duration=100, loop=0,
                   optimize=True)
    frames[0].save(output / "demo-mosaic-ja.webp", save_all=True, append_images=frames[1:], duration=100, loop=0,
                   quality=80)


def capture(code: str, output: Path, work: Path) -> int:
    os.environ["SUMIRE_SETTINGS_FILE"] = str(work / "profile" / "settings.json")
    from sumire.preferences import Preferences
    # A finished first start: separate-folder saving, metadata removed on save, records in the app folder.
    Preferences().save({"storage": "app", "language": code, "hide_quit_confirmation": True,
                        "settings": {"overwrite": False, "strip_metadata": True, "metadata_backup": True}})
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    app = QApplication([sys.argv[0]])
    from sumire import i18n
    i18n.set_language(code)
    from sumire.__main__ import configure
    configure(app)
    from sumire import workspace_tabs
    window = workspace_tabs.WorkspaceWindow()
    if QApplication.platformName() != "offscreen":
        window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    window.resize(1440, 900)
    window.show()
    images = work / "images"
    prepare_images(images)
    window.open_inputs([str(images)])
    page = window.current_workspace()
    wait(app, lambda: page.document is not None and page.canvas.ready and not page.busy())
    settle(app)
    # Sort a few images, then come back to the first one and hide its signature.
    first = page.document.path
    for label in ("accepted", "rejected", "pending"):
        shown = page.document.path
        page.set_review_label(label)
        settle(app, 0.2)
        if page.document.path == shown:  # 「ラベルを付けたら次へ」 is off
            page.navigate(1)
        wait(app, lambda: page.document is not None and page.document.path != shown and page.canvas.ready and not page.busy())
    for _ in range(3):
        page.navigate(-1)
        wait(app, lambda: page.document is not None and page.canvas.ready and not page.busy())
    assert page.document.path == first
    settle(app)
    page.brush.setValue(90)
    page.strength.setValue(18)
    canvas = page.canvas

    def at(x, y):
        """A point of the 1200×900 picture on the canvas (which may show a reduced copy)."""
        shown = QPointF(x * canvas.image.width() / 1200, y * canvas.image.height() / 900)
        return (shown * canvas.scale + canvas.offset).toPoint()
    wait(app, lambda: canvas.ready and not page.busy())  # the new strength is being prepared
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=at(850, 805))
    for x in range(850, 1121, 30):
        QTest.mouseMove(canvas, at(x, 805))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=at(1120, 805))
    wait(app, lambda: page.document.revision > 0 and page.document.saved_revision == page.document.revision
         and not page.saving, 60)
    settle(app, 0.6)
    output.mkdir(parents=True, exist_ok=True)
    window.grab().save(str(output / f"main-{code}.png"))
    if code == "ja":
        animate(app, page, output)
        from sumire.editor_dialogs import MetadataDialog
        from sumire.metadata import describe_metadata
        from sumire.i18n import tr
        source = images / "illustration_02.png"
        dialog = MetadataDialog(tr("{where}：{source}").format(where=tr("画像"), source=source.name),
                                describe_metadata(source),
                                tr("対応している形式の検査結果です。意味の分からない情報は「不明」として載せています。"
                                   "未知の方法で埋め込まれた情報は表示できません。"), page)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, QApplication.platformName() != "offscreen")
        dialog.show()
        settle(app)
        dialog.grab().save(str(output / "metadata-ja.png"))
        dialog.close()
        from sumire.onboarding import FirstRunDialog
        first = FirstRunDialog(window)
        first.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, QApplication.platformName() != "offscreen")
        first.show()
        settle(app)
        first.grab().save(str(output / "first-run-ja.png"))
        first.close()
    workspace_tabs.QUIT_CONFIRMATION["enabled"] = False
    window.close()
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--language", choices=("ja", "en", "zh_CN"))
    args = parser.parse_args()
    if args.language:
        with tempfile.TemporaryDirectory(prefix="sumire-screens-") as work:
            return capture(args.language, args.output.resolve(), Path(work))
    failed = []
    for code in ("ja", "en", "zh_CN"):
        result = subprocess.run([sys.executable, "-m", "scripts.capture_screens", "--output", str(args.output.resolve()),
                                 "--language", code], cwd=Path(__file__).resolve().parents[1], timeout=300)
        if result.returncode:
            failed.append(code)
    if failed:
        raise SystemExit(f"failed: {failed}")
    print(f"Saved screenshots in {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
