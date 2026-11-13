"""Repeatable synthetic benchmarks; run separately for each source revision.

QT_QPA_PLATFORM=offscreen python -m scripts.benchmark_performance --samples 3
Results are reference timings, not a guarantee for real images or Windows.
"""
import argparse
import json
import random
import statistics
import tempfile
import time
from pathlib import Path

from PIL import Image
from PySide6.QtWidgets import QApplication

from sumire import imaging
from sumire.imaging import Document, Stroke, Tool, load_image
from sumire.window import Window


def wait_until(app, condition, timeout=30):
    deadline = time.monotonic() + timeout
    while not condition():
        app.processEvents()
        if time.monotonic() >= deadline:
            raise RuntimeError("Benchmark operation timed out")
        time.sleep(0.002)
    app.processEvents()


def measure(function, samples):
    function()  # warm-up
    elapsed = []
    for _ in range(samples):
        start = time.perf_counter()
        function()
        elapsed.append((time.perf_counter() - start) * 1000)
    return round(statistics.median(elapsed), 3)


def benchmark(samples):
    import os
    app = QApplication.instance() or QApplication([])
    results = {"image_size": [3840, 2160], "samples": samples, "timing": "median after warm-up, milliseconds"}
    with tempfile.TemporaryDirectory(prefix="sumire-benchmark-") as raw:
        root = Path(raw)
        previous_settings = os.environ.get("SUMIRE_SETTINGS_FILE")
        os.environ["SUMIRE_SETTINGS_FILE"] = str(root / "settings.json")
        try:
            source = Image.frombytes("L", (3840, 2160), random.Random(12345).randbytes(3840 * 2160)).convert("RGBA")
            for suffix in ("png", "jpg"):
                path = root / f"synthetic.{suffix}"
                source.convert("RGB").save(path)
                def thumbnail():
                    if hasattr(imaging, "load_thumbnail"):
                        image = imaging.load_thumbnail(path)
                    else:
                        image = load_image(path)
                        image.thumbnail((256, 256))
                    assert image.size == (256, 144)
                results[f"thumbnail_{suffix}_ms"] = measure(thumbnail, samples)

            document = Document(root / "stroke.png", source)
            effect = Image.new("RGBA", source.size, "black")
            def begin_stroke():
                stroke = Stroke(document, Tool("fill", diameter=10), effect)
                stroke.cancel()
            results["stroke_begin_ms"] = measure(begin_stroke, samples)
            stroke = Stroke(document, Tool("fill", diameter=10), effect)
            stroke.add((500, 500))
            results["stroke_snapshot_bytes"] = (sum(pixels.width * pixels.height * 5 for pixels, mask in stroke.tiles.values())
                                                if hasattr(stroke, "tiles") else document.image.width * document.image.height * 5)
            stroke.cancel()
            del document, effect, stroke

            window = Window()
            try:
                window.watch_timer.stop()
                path = root / "synthetic.png"
                window.open_inputs([str(path)])
                wait_until(app, lambda: window.document is not None and window.canvas.ready and window.effect_job is None)
                window.save()
                wait_until(app, lambda: not window.saving and window.document.output is not None)
                def reopen():
                    window.documents.clear()
                    window._load_index(0)
                    wait_until(app, lambda: not window.loading and window.canvas.ready and window.effect_job is None)
                results["reopen_saved_png_ms"] = measure(reopen, samples)
                window.canvas.set_document(None)
                window.document = None
                window.documents.clear()
                folder = root / "directory"
                folder.mkdir()
                paths = [folder / f"{n:05}.png" for n in range(10000)]
                for entry in paths:
                    entry.touch()
                window.model.set_paths(paths)
                window.watched_folders = {folder}
                window.poll_folders()
                if hasattr(window, "watch_monitor"):
                    wait_until(app, lambda: window.watch_monitor.job is None)
                    window.watch_monitor.dirty = False
                results["idle_monitor_10000_files_ms"] = measure(window.poll_folders, samples)
            finally:
                window.auto.setChecked(False)
                window.close()
        finally:
            if previous_settings is None:
                os.environ.pop("SUMIRE_SETTINGS_FILE", None)
            else:
                os.environ["SUMIRE_SETTINGS_FILE"] = previous_settings
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=3)
    args = parser.parse_args()
    if args.samples < 1:
        parser.error("samples must be positive")
    print(json.dumps(benchmark(args.samples), ensure_ascii=False, indent=2))
