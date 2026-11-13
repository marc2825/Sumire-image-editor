import pytest
from PIL import Image, ImageChops

from sumire.imaging import load_image
from sumire.stealth import remove_stealth, stealth_channels


@pytest.mark.parametrize("channel", ["alpha", "rgb"])
@pytest.mark.parametrize("compressed", [False, True])
def test_removes_entire_stealth_carrier_without_decoding(patterned, encode_stealth, decode_stealth, channel, compressed):
    embedded = encode_stealth(patterned, channel, compressed, trailing=b"synthetic trailing FEC data" * 10)
    before = embedded.tobytes()
    assert "private NovelAI prompt" in decode_stealth(embedded, channel)["Description"]
    assert stealth_channels(embedded) == (channel,)
    cleaned = remove_stealth(embedded)
    assert embedded.tobytes() == before
    assert cleaned.size == embedded.size
    assert not stealth_channels(cleaned)
    assert decode_stealth(cleaned, "alpha") is None
    assert decode_stealth(cleaned, "rgb") is None
    if channel == "alpha":
        assert cleaned.convert("RGB").tobytes() == patterned.convert("RGB").tobytes()
        # Entire carrier is gone, including payload and error-correction data;
        # erasing only the signature would leave recoverable private bytes.
        assert cleaned.getchannel("A").getextrema() == (255, 255)
    else:
        assert all(value & 1 == 0 for value in cleaned.convert("RGB").tobytes())
        assert cleaned.getchannel("A").tobytes() == embedded.getchannel("A").tobytes()
    assert all(extrema[1] <= 1 for extrema in ImageChops.difference(embedded, cleaned).getextrema())


@pytest.mark.parametrize("size", [(1, 4096), (4096, 1), (7, 600)])
def test_column_order_and_narrow_images(encode_stealth, decode_stealth, size):
    embedded = encode_stealth(Image.new("RGBA", size, (80, 120, 160, 255)))
    assert decode_stealth(embedded) is not None
    assert stealth_channels(embedded) == ("alpha",)
    assert decode_stealth(remove_stealth(embedded)) is None


def test_real_transparency_is_retained(encode_stealth):
    image = Image.new("RGBA", (160, 120))
    image.putdata([(40, 80, 120, index % 256) for index in range(160 * 120)])
    embedded = encode_stealth(image)
    cleaned = remove_stealth(embedded)
    assert cleaned.convert("RGB").tobytes() == image.convert("RGB").tobytes()
    assert cleaned.getchannel("A").getextrema() == (0, 255)
    assert all(extrema[1] <= 1 for extrema in ImageChops.difference(embedded, cleaned).getextrema())


@pytest.mark.parametrize("mode", ["RGB", "RGBA", "LA", "P", "L", "CMYK"])
def test_ordinary_images_are_unchanged(patterned, mode):
    image = patterned.convert(mode)
    before = image.tobytes()
    assert not stealth_channels(image)
    assert remove_stealth(image).tobytes() == before


def test_load_cleans_stealth_before_exif_rotation(tmp_path, patterned, encode_stealth, decode_stealth):
    path = tmp_path / "rotated.png"
    exif = Image.Exif()
    exif[274] = 6
    encode_stealth(patterned).save(path, exif=exif)
    pixels = load_image(path)
    assert pixels.size == (patterned.height, patterned.width)
    assert pixels.convert("RGB").tobytes() == patterned.transpose(Image.Transpose.ROTATE_270).convert("RGB").tobytes()
    assert pixels.getchannel("A").getextrema() == (255, 255)
    assert decode_stealth(pixels) is None
    assert not pixels.info and not pixels.getexif()
