import gzip
import json
import os

# Native interaction can be tested by explicitly setting QT_QPA_PLATFORM=xcb/windows.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image


@pytest.fixture(scope="session", autouse=True)
def bundled_fonts(qapp):
    """Lay out with the font the app ships with (Noto Sans JP), as the app does at start."""
    from sumire.theme import install_fonts
    return install_fonts()


@pytest.fixture(autouse=True)
def isolated_preferences(tmp_path, monkeypatch):
    monkeypatch.setenv("SUMIRE_SETTINGS_FILE", str(tmp_path / "settings.json"))


@pytest.fixture(autouse=True)
def quiet_overwrite_notice(monkeypatch, tmp_path):
    """The first-overwrite explanation has its own test; elsewhere it is already acknowledged.

    Originals kept before overwriting go to a per-test folder, not the system temp folder.
    """
    from sumire import backups, window, workspace_tabs
    monkeypatch.setitem(window.OVERWRITE_NOTICE, "shown", True)
    # Closing the app asks first; that dialog has its own test.
    monkeypatch.setitem(workspace_tabs.QUIT_CONFIRMATION, "enabled", False)
    # Most tests check that saving removes metadata; keeping it is covered by tests that switch this back off.
    monkeypatch.setattr(window, "STRIP_METADATA_DEFAULT", True)
    store = backups.OriginalBackups(tmp_path)
    monkeypatch.setattr(backups, "_store", store)
    from sumire import i18n
    i18n.set_language("ja")
    yield
    store.cleanup()
    i18n.set_language("ja")  # a test that switched the language must not affect the next


@pytest.fixture
def batch_approved(monkeypatch):
    """Processing tests approve the dialog; confirmation behavior has dedicated GUI tests."""
    from sumire.window import Window
    monkeypatch.setattr(Window, "confirm_batch_deletion", lambda self, paths: True)


@pytest.fixture
def patterned():
    image = Image.new("RGBA", (160, 120))
    image.putdata([((x * 19 + y * 3) % 256, (y * 29) % 256, (x * 7 + y * 11) % 256, 255)
                   for y in range(120) for x in range(160)])
    return image


@pytest.fixture
def encode_stealth():
    """Independent synthetic encoder following the public column-first format."""
    def encode(image, channel="alpha", compressed=True, trailing=b""):
        image = image.convert("RGBA")
        payload = json.dumps({
            "Software": "NovelAI",
            "Description": "synthetic private NovelAI prompt",
            "Comment": json.dumps({"prompt": "synthetic private NovelAI prompt", "uc": "private negative prompt", "seed": 12345}),
        }).encode()
        body = gzip.compress(payload, mtime=0) if compressed else payload
        signature = f"stealth_{'png' if channel == 'alpha' else 'rgb'}{'comp' if compressed else 'info'}".encode()
        data = signature + (len(body) * 8).to_bytes(4, "big") + body + trailing
        channels = (3,) if channel == "alpha" else (0, 1, 2)
        bits = [int(bit) for byte in data for bit in f"{byte:08b}"]
        assert len(bits) <= image.width * image.height * len(channels)
        pixels = image.load()
        for index, bit in enumerate(bits):
            pixel_index, offset = divmod(index, len(channels))
            x, y = divmod(pixel_index, image.height)
            values = list(pixels[x, y])
            values[channels[offset]] = (values[channels[offset]] & 254) | bit
            pixels[x, y] = tuple(values)
        return image
    return encode


@pytest.fixture
def decode_stealth():
    """Read the payload independently; no production detection/removal helpers."""
    def decode(image, channel="alpha"):
        image = image.convert("RGBA")
        if channel == "alpha":
            carrier = image.getchannel("A")
        else:
            carrier = image.convert("RGB")
        raw = carrier.transpose(Image.Transpose.TRANSPOSE).tobytes()
        packed = bytes(sum((raw[offset + bit] & 1) << (7 - bit) for bit in range(8))
                       for offset in range(0, len(raw) - 7, 8))
        prefix = b"stealth_png" if channel == "alpha" else b"stealth_rgb"
        if packed[:15] not in {prefix + b"comp", prefix + b"info"}:
            return None
        size = int.from_bytes(packed[15:19], "big") // 8
        body = packed[19:19 + size]
        if packed[:15].endswith(b"comp"):
            body = gzip.decompress(body)
        return json.loads(body)
    return decode

