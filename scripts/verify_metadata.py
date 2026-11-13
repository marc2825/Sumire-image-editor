"""Optional independent verifier. Runs a locally installed ExifTool, offline."""
import argparse
import json
import shutil
import subprocess
from pathlib import Path

from PIL import Image

from sumire.export import verify_export
from sumire.imaging import ImageProblem


def main():
    parser = argparse.ArgumentParser(description="出力の内部構造・隠しメタデータとExifToolで検証")
    parser.add_argument("image", type=Path)
    args = parser.parse_args()
    try:
        with Image.open(args.image) as image:
            result = verify_export(args.image, image.size, image.format)
    except ImageProblem as error:
        parser.exit(1, f"FAIL: {error}\n")
    executable = shutil.which("exiftool")
    if not executable:
        parser.exit(2, "内部検証PASS / ExifTool NOT RUN（未インストール）\n")
    process = subprocess.run([executable, "-j", "-G1", "-a", str(args.image.resolve())], capture_output=True, check=True)
    fields = json.loads(process.stdout)[0]
    # The strict internal chunk/marker allowlist also rejects unknown PNG text keys.
    prohibited = ("ExifIFD:", "IFD0:", "IFD1:", "GPS:", "XMP", "IPTC:", "ICC_Profile:", "Photoshop:")
    if any(key.startswith(prohibited) for key in fields):
        parser.exit(1, "FAIL: 付加メタデータを検出\n")
    print(f"PASS: {result.format}, {result.size[0]}×{result.size[1]}, 内部構造・隠しメタデータ検査 / ExifTool")


if __name__ == "__main__":
    main()

