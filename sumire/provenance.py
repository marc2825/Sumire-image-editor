"""Content Credentials (C2PA) and AI-generation marks in image files, read for display.

Images made with ChatGPT / the OpenAI API, Claude, Adobe Firefly, Google's tools and
others carry a signed C2PA manifest: who signed it, the tool that made the image and
whether it was made by AI. It sits in its own part of the file (PNG caBX chunk, JPEG
APP11 segments, WebP C2PA chunk, AVIF/HEIF uuid box), so saving without metadata
removes it like any other metadata. Signatures are read, not verified. Watermarks
hidden in the pixels themselves (such as SynthID) are not metadata and are not read.
"""
from __future__ import annotations
from .i18n import tr

from datetime import datetime, timezone
import io
import re
import struct

LIMIT = 32 * 1024 * 1024
STORE = b"jumdc2pa"  # a JUMBF description box of the C2PA manifest store type
C2PA_UUID = bytes.fromhex("d8fec3d61b0e483c92975828877ec481")
SOURCE = re.compile(r"digitalsourcetype/([A-Za-z]+)")
AI_SOURCES = {"trainedAlgorithmicMedia", "compositeWithTrainedAlgorithmicMedia"}
SOURCE_TYPES = {
    "trainedAlgorithmicMedia": tr("AIで生成"),
    "compositeWithTrainedAlgorithmicMedia": tr("AIを使って合成・編集"),
    "algorithmicMedia": tr("プログラムで生成（AIではない）"),
    "compositeSynthetic": tr("合成"),
    "digitalCapture": tr("撮影"),
    "digitalCreation": tr("デジタルで制作"),
    "digitalArt": tr("デジタルで制作"),
}
ORGANIZATION, COMMON_NAME = b"\x55\x04\x0a", b"\x55\x04\x03"


def source_text(code):
    """「AIで生成（trainedAlgorithmicMedia）」 for an IPTC digital source type."""
    return tr("{meaning}（{code}）").format(meaning=SOURCE_TYPES[code], code=code) if code in SOURCE_TYPES else code


def xmp_sources(xmp):
    """IPTC digital source types named in XMP (Midjourney, Google and others write them)."""
    text = xmp.decode("utf-8", "replace") if isinstance(xmp, bytes) else str(xmp or "")
    return list(dict.fromkeys(SOURCE.findall(text)))


# --- Finding the manifest store -------------------------------------------------------

def _extract(data):
    """The manifest store (a whole JUMBF superbox) inside ``data``, or None."""
    index = data.find(STORE)
    if index < 12 or data[index - 8:index - 4] != b"jumb":
        return None
    size = int.from_bytes(data[index - 12:index - 8], "big")
    start = index - 12
    if size < 16 or start + size > len(data):
        return None
    return data[start:start + size]


def _jpeg(stream):
    """APP11 segments are ISO 19566-5 boxes split into parts: "JP", instance, sequence, box."""
    stream.seek(2)
    payloads, total = [], 0
    while True:
        marker = stream.read(2)
        if len(marker) < 2 or marker[0] != 0xFF:
            break
        code = marker[1]
        if code == 0xFF:
            stream.seek(-1, 1)
            continue
        if code in {0x01, 0xD8} or 0xD0 <= code <= 0xD7:
            continue
        if code in {0xD9, 0xDA}:
            break
        header = stream.read(2)
        size = int.from_bytes(header, "big") if len(header) == 2 else 0
        if size < 2:
            break
        if code != 0xEB:
            stream.seek(size - 2, 1)
            continue
        payload = stream.read(size - 2)
        total += len(payload)
        if total > LIMIT:
            break
        payloads.append(payload)
    return jpeg_segments_store(payloads)


def jpeg_segments_store(payloads):
    """The manifest store from the payloads of a JPEG's APP11 segments, joined in order."""
    parts = {}
    for payload in payloads:
        if len(payload) >= 16 and payload[:2] == b"JP":
            instance, sequence = struct.unpack(">HI", payload[2:8])
            parts.setdefault(instance, {})[sequence] = payload[8:]
    for numbered in parts.values():
        ordered = [numbered[key] for key in sorted(numbered)]
        # Later parts repeat the box header (length and type) before continuing the data.
        store = _extract(ordered[0] + b"".join(part[8:] for part in ordered[1:]))
        if store:
            return store
    return None


def _chunks(stream, start, png):
    """(kind, size) of each top-level PNG or RIFF (WebP) chunk, with the stream at its data."""
    stream.seek(start)
    while True:
        raw = stream.read(8)
        if len(raw) < 8:
            return
        if png:
            size, kind = struct.unpack(">I4s", raw)
            following = size + 4  # the CRC
        else:
            kind, size = struct.unpack("<4sI", raw)
            following = size + size % 2  # padded to an even size
        position = stream.tell()
        yield kind, size
        stream.seek(position + following)


def read_store(stream, format):
    """The C2PA manifest store of an encoded image, read without decoding its pixels."""
    try:
        if format == "JPEG":
            return _jpeg(stream)
        if format == "PNG":
            for kind, size in _chunks(stream, 8, png=True):
                if kind == b"caBX":
                    return _extract(stream.read(min(size, LIMIT)))
                if kind == b"IEND":
                    break
        elif format == "WEBP":
            for kind, size in _chunks(stream, 12, png=False):
                if kind == b"C2PA":
                    return _extract(stream.read(min(size, LIMIT)))
        elif format in {"AVIF", "HEIF"}:
            stream.seek(0)
            while True:
                raw = stream.read(8)
                if len(raw) < 8:
                    break
                size, kind = struct.unpack(">I4s", raw)
                header = 8
                if size == 1:
                    size, header = struct.unpack(">Q", stream.read(8))[0], 16
                if size < header:
                    break
                if kind == b"uuid":
                    data = stream.read(min(size - header, LIMIT))
                    if data[:16] == C2PA_UUID:
                        return _extract(data[16:])
                    stream.seek(size - header - len(data), 1)
                else:
                    stream.seek(size - header, 1)
    except (OSError, ValueError, struct.error):
        return None
    return None


def file_store(path, format):
    try:
        with open(path, "rb") as stream:
            return read_store(stream, format)
    except OSError:
        return None


def raw_store(raw, format):
    return read_store(io.BytesIO(raw), format)


# --- Reading it: JUMBF boxes, CBOR, the signer's certificate --------------------------

def _boxes(data):
    offset = 0
    while offset + 8 <= len(data):
        size, kind = struct.unpack_from(">I4s", data, offset)
        header = 8
        if size == 1 and offset + 16 <= len(data):
            size, header = struct.unpack_from(">Q", data, offset + 8)[0], 16
        elif size == 0:
            size = len(data) - offset
        if size < header or offset + size > len(data):
            return
        yield kind, data[offset + header:offset + size]
        offset += size


def _superbox(content):
    """(label, child boxes) of a JUMBF superbox: its description box gives the label."""
    children = list(_boxes(content))
    if not children or children[0][0] != b"jumd":
        return None, []
    description = children[0][1]
    label = ""
    if len(description) > 17 and description[16] & 2:
        end = description.find(b"\0", 17)
        label = description[17:end if end >= 0 else None].decode("utf-8", "replace")
    return label, children[1:]


def _labelled(children):
    return [_superbox(content) for kind, content in children if kind == b"jumb"]


def _content(children):
    for kind, content in children:
        if kind == b"cbor":
            return _cbor(content)
        if kind == b"json":
            import json
            return json.loads(content.decode("utf-8"))
    return None


def _cbor(data):
    value, _offset = _cbor_item(data, 0, 0)
    return value


def _cbor_item(data, offset, depth):
    if depth > 40 or offset >= len(data):
        raise ValueError()
    initial = data[offset]
    major, info = initial >> 5, initial & 31
    offset += 1
    if info < 24:
        value = info
    elif info <= 27:
        size = 1 << (info - 24)
        if offset + size > len(data):
            raise ValueError()
        value = int.from_bytes(data[offset:offset + size], "big")
        offset += size
    elif info == 31 and major in {2, 3, 4, 5}:
        value = None
    else:
        raise ValueError()
    if major == 0:
        return value, offset
    if major == 1:
        return -1 - value, offset
    if major in {2, 3}:
        if value is None:
            pieces = []
            while data[offset] != 0xFF:
                piece, offset = _cbor_item(data, offset, depth + 1)
                pieces.append(piece)
            joined = (b"" if major == 2 else "").join(pieces)
            return joined, offset + 1
        if offset + value > len(data):
            raise ValueError()
        chunk = data[offset:offset + value]
        return (chunk if major == 2 else chunk.decode("utf-8", "replace")), offset + value
    if major in {4, 5}:
        if value is not None and value > len(data) - offset:
            raise ValueError()
        items = []
        count = 0
        while (value is None and data[offset] != 0xFF) or (value is not None and count < value * (major - 3)):
            item, offset = _cbor_item(data, offset, depth + 1)
            items.append(item)
            count += 1
        if value is None:
            offset += 1
        if major == 4:
            return items, offset
        keys = [key if isinstance(key, (int, str, bytes)) else repr(key) for key in items[::2]]
        return dict(zip(keys, items[1::2])), offset
    if major == 6:
        return _cbor_item(data, offset, depth + 1)  # a tagged value: keep the value
    if info == 20:
        return False, offset
    if info == 21:
        return True, offset
    if info in {25, 26, 27}:
        size = 1 << (info - 24)
        return struct.unpack({2: ">e", 4: ">f", 8: ">d"}[size], value.to_bytes(size, "big"))[0], offset
    return None, offset


def _der(data, offset):
    if offset + 2 > len(data):
        raise ValueError()
    tag, length = data[offset], data[offset + 1]
    offset += 2
    if length & 0x80:
        count = length & 0x7F
        if not 0 < count <= 4 or offset + count > len(data):
            raise ValueError()
        length = int.from_bytes(data[offset:offset + count], "big")
        offset += count
    if offset + length > len(data):
        raise ValueError()
    return tag, data[offset:offset + length], offset + length


def _der_children(data):
    offset = 0
    while offset < len(data):
        tag, value, offset = _der(data, offset)
        yield tag, value


def certificate_subject(certificate):
    """Organization (or common name) of a DER certificate's subject."""
    _tag, body, _end = _der(certificate, 0)
    _tag, tbs = next(_der_children(body))
    fields = [value for tag, value in _der_children(tbs) if tag != 0xA0]  # without the explicit version
    names = {}
    for _tag, rdn in _der_children(fields[4]):
        for _tag, attribute in _der_children(rdn):
            parts = list(_der_children(attribute))
            if len(parts) == 2 and parts[0][0] == 6:
                tag, value = parts[1]
                names[parts[0][1]] = value.decode("utf-16-be" if tag == 0x1E else "utf-8", "replace")
    return names.get(ORGANIZATION) or names.get(COMMON_NAME)


def _signer(signature):
    if not isinstance(signature, list) or len(signature) < 2:
        return None
    headers = []
    if isinstance(signature[0], bytes) and signature[0]:
        headers.append(_cbor(signature[0]))
    headers.append(signature[1])
    for header in headers:
        if isinstance(header, dict):
            chain = header.get(33, header.get("x5chain"))
            first = chain[0] if isinstance(chain, list) and chain else chain
            if isinstance(first, bytes):
                return certificate_subject(first)
    return None


def _agent(value):
    if isinstance(value, dict):
        return " ".join(str(value[key]) for key in ("name", "version") if isinstance(value.get(key), (str, int)))
    return value if isinstance(value, str) else None


def _strings(value, depth=0):
    if depth > 20:
        return
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item, depth + 1)


TIMESTAMP = re.compile(rb"\x18[\x0f-\x18](\d{14}(?:\.\d+)?Z)")


def _timestamp(signature):
    """The time a timestamp authority vouched for (RFC 3161 genTime), from a COSE signature."""
    unprotected = signature[1] if isinstance(signature, list) and len(signature) > 1 else None
    if not isinstance(unprotected, dict):
        return None
    for key in ("sigTst2", "sigTst"):
        tokens = unprotected.get(key, {}).get("tstTokens") if isinstance(unprotected.get(key), dict) else None
        for token in tokens if isinstance(tokens, list) else []:
            value = token.get("val") if isinstance(token, dict) else None
            # In the token, TSTInfo (and its genTime) comes before any certificate's dates.
            match = TIMESTAMP.search(value) if isinstance(value, bytes) else None
            if match:
                return datetime.strptime(match.group(1)[:14].decode("ascii"), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    return None


def parse_time(text):
    """An ISO 8601 time (any fraction of a second), or None."""
    match = re.fullmatch(r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?)(?:\.\d+)?(Z|[+-]\d{2}:?\d{2})?", str(text).strip())
    if not match:
        return None
    zone = match.group(2) or ""
    try:
        return datetime.fromisoformat(match.group(1).replace(" ", "T") + ("+00:00" if zone == "Z" else zone))
    except ValueError:
        return None


def local_text(moment):
    """「2026-11-14 12:23:43 +09:00」 in this PC's time zone (a time without a zone stays as it is)."""
    if moment.tzinfo is None:
        return f"{moment:%Y-%m-%d %H:%M:%S}"
    moment = moment.astimezone()
    offset = moment.strftime("%z")
    return f"{moment:%Y-%m-%d %H:%M:%S} {offset[:3]}:{offset[3:]}"


def read_manifest(store):
    """What the active manifest of a store says (a dict), or None when it cannot be read."""
    try:
        label, manifests = _superbox(next(_boxes(store))[1])
        manifests = _labelled(manifests)
        if label != "c2pa" or not manifests:
            return None
        _label, active = manifests[-1]  # the active manifest is the last one
        parts = {name: children for name, children in _labelled(active)}
        claim = _content(parts.get("c2pa.claim.v2") or parts.get("c2pa.claim") or []) or {}
        generators = claim.get("claim_generator_info")
        generators = [generators] if isinstance(generators, dict) else generators if isinstance(generators, list) else []
        info = {"manifests": len(manifests), "sources": [], "agents": [], "actions": [], "created": None, "times": [],
                "exif": {}, "signer": None, "signed": None,
                "generator": ", ".join(filter(None, (_agent(item) for item in generators))) or (
                    claim.get("claim_generator") if isinstance(claim.get("claim_generator"), str) else "")}
        for name, children in _labelled(parts.get("c2pa.assertions", [])):
            try:
                value = _content(children)
            except (ValueError, UnicodeDecodeError, IndexError):
                continue
            info["sources"].extend(code for text in _strings(value) for code in SOURCE.findall(text))
            if name.startswith("c2pa.actions") and isinstance(value, dict):
                for action in value.get("actions", []) if isinstance(value.get("actions"), list) else []:
                    if isinstance(action, dict):
                        info["actions"].append(action.get("action"))
                        info["agents"].append(_agent(action.get("softwareAgent")))
                        moment = parse_time(action["when"]) if isinstance(action.get("when"), str) else None
                        if moment and action.get("action") == "c2pa.created":
                            info["created"] = moment
                        elif moment:
                            info["times"].append(moment)
            if name.startswith("stds.exif") and isinstance(value, dict):
                # EXIF carried inside the manifest (some cameras and phones), as JSON-LD.
                info["exif"].update({key: item for key, item in value.items()
                                     if isinstance(key, str) and key.startswith("exif:") and isinstance(item, (str, int, float))})
        info["created"] = info["created"] or min(info["times"], default=None)
        try:
            signature = _content(parts.get("c2pa.signature", []))
            info["signer"], info["signed"] = _signer(signature), _timestamp(signature)
        except (ValueError, StopIteration, IndexError, UnicodeDecodeError):
            pass
        return info
    except (ValueError, StopIteration, IndexError, UnicodeDecodeError, struct.error):
        return None


def describe_store(store):
    """(item, text) rows of a manifest store for the metadata window; AI-made first."""
    info = read_manifest(store)
    if info is None:
        return [(tr("C2PAの記録"), tr("内容を読み取れません（{count:,}バイト）").format(count=len(store)))]
    rows = []
    sources = list(dict.fromkeys(info["sources"]))
    if sources:
        rows.append((tr("作成の方法"), ", ".join(source_text(code) for code in sources)))
    if info["signer"]:
        rows.append((tr("署名者（検証はしていません）"), info["signer"]))
    if info["generator"]:
        rows.append((tr("作成したツール"), info["generator"]))
    agents = list(dict.fromkeys(filter(None, info["agents"])))
    if agents:
        rows.append((tr("使われたAI・ソフトウェア"), ", ".join(agents)))
    actions = list(dict.fromkeys(item for item in info["actions"] if isinstance(item, str)))
    if actions:
        rows.append((tr("記録された操作"), ", ".join(actions)))
    rows.append((tr("C2PAの記録"), tr("マニフェスト {count}件 · {size:,}バイト").format(count=info["manifests"], size=len(store))))
    return rows


def has_thumbnail(store):
    """Whether any manifest holds a thumbnail (a small copy of an image); an unreadable store counts as yes."""
    try:
        label, manifests = _superbox(next(_boxes(store))[1])
        if label != "c2pa":
            return True
        for _name, children in _labelled(manifests):
            for part, assertions in _labelled(children):
                if part == "c2pa.assertions" and any((name or "").startswith("c2pa.thumbnail") for name, _ in _labelled(assertions)):
                    return True
        return False
    except (ValueError, StopIteration, IndexError, UnicodeDecodeError, struct.error):
        return True


def store_is_ai(store):
    # In the encoded bytes a text ends without a separator, so look for each whole code.
    return any(b"digitalsourcetype/" + code.encode() in store for code in AI_SOURCES)
