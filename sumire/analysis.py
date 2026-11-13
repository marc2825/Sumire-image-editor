"""Bounded image comparison signatures and duplicate grouping."""
from .i18n import tr
from collections import defaultdict

from PIL import Image

from .export import Cancelled, check_cancel, file_digest
from .imaging import load_image


def difference_hash(image):
    pixels = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS).tobytes()
    result = 0
    for y in range(8):
        for x in range(8):
            result = (result << 1) | (pixels[y * 9 + x] > pixels[y * 9 + x + 1])
    return result


class HashTree:
    """BK tree avoids comparing every image against every preceding image."""
    def __init__(self):
        self.root = None

    def add(self, value, index):
        if self.root is None:
            self.root = (value, [index], {})
            return
        node = self.root
        while True:
            distance = (node[0] ^ value).bit_count()
            if distance == 0:
                node[1].append(index)
                return
            if distance not in node[2]:
                node[2][distance] = (value, [index], {})
                return
            node = node[2][distance]

    def find(self, value, limit):
        stack = [self.root] if self.root else []
        while stack:
            node = stack.pop()
            distance = (node[0] ^ value).bit_count()
            if distance <= limit:
                yield from node[1]
            stack.extend(child for edge, child in node[2].items() if distance - limit <= edge <= distance + limit)


def find_duplicates(paths, *, similar=False, threshold=6, cancel=None, progress=None):
    groups, errors = [], {}
    exact = defaultdict(list)
    tree = HashTree()
    parents = list(range(len(paths)))
    def root(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index
    good = []
    for number, path in enumerate(paths):
        check_cancel(cancel)
        try:
            if similar:
                image = load_image(path)
                value = difference_hash(image)
                for match in tree.find(value, threshold):
                    parents[root(number)] = root(match)
                tree.add(value, number)
                good.append(number)
            else:
                exact[file_digest(path)].append(path)
        except Cancelled:
            raise
        except (OSError, ValueError) as error:
            errors[path] = tr("画像を読み込めません。") if not str(error) else tr("画像の読み込み・検査に失敗しました。")
        finally:
            if progress:
                progress(number + 1, len(paths))
    if similar:
        grouped = defaultdict(list)
        for index in good:
            grouped[root(index)].append(paths[index])
        groups = [group for group in grouped.values() if len(group) > 1]
    else:
        groups = [group for group in exact.values() if len(group) > 1]
    return groups, errors
