# 重複と似た画像の判定

「重複を削除」が同じ画像をどう見分けているかと、似た画像を見分けるための仕組み（今は画面から使っていません）です。

## 重複を削除（完全に同じファイル）

タブ内のすべての画像について、ファイルの中身のSHA-256（ハッシュ値）を計算し、値が同じものを1組にまとめます。

- SHA-256は、ファイルの中身が1バイトでも違えば、まったく違う値になります。値が同じなら、中身も同じと見なせます。
- **ファイルとして完全に同じものだけ**が重複になります。見た目が同じでも、形式・メタデータ・JPEGの圧縮の具合が違えば、重複とは見なしません。
- 各組の1枚目（一覧で先にある画像）を残す設定で確認画面を出し、チェックした画像をごみ箱へ移します。

## 似た画像の見分け方（dHash）

コードには、見た目が似ている画像をまとめる仕組みもあります。以前の「似ている画像を探す」で使っていたもので、今は画面からは使っていません。[今後の予定](../../ROADMAP.md)にある、似た画像のまとめ（クラスタリング）の土台にする予定です。

1. 画像を白黒にし、横9×縦8画素に縮小します。
2. 各行で隣り合う画素の明るさを比べ、左が明るければ1、そうでなければ0とします。8行×8か所で、64ビットの値（dHash）になります。
3. 2枚のdHashで、違うビットの数（ハミング距離）を数えます。初期値では6ビット以下なら似ていると見なします。

縮小してから比べるので、大きさの違い、明るさの変化、JPEGの圧縮のような小さな違いには強く、切り抜き・回転・反転・大きな加工には弱い方法です。

### 大量の画像での比べ方

すべての組み合わせを比べると、画像の数の2乗に比例して時間がかかります。そこで次の2つを使います。

- **BK木**：ハミング距離の性質（三角不等式）を使って、距離が離れていると分かっている画像を比較せずに飛ばします。
- **Union-Find**：「AとBが似ている」「BとCが似ている」なら、A・B・Cを1組にまとめます。このため、AとCがあまり似ていなくても同じ組になることがあります（連鎖）。

## 該当するコード

| 場所 | 内容 |
| --- | --- |
| [`sumire/analysis.py`](../../sumire/analysis.py) | `find_duplicates`（重複・似た画像の組の作成）、`difference_hash`（dHash）、`HashTree`（BK木） |
| [`sumire/export.py`](../../sumire/export.py) | `file_digest`（SHA-256） |
| [`sumire/workbench.py`](../../sumire/workbench.py) | 「重複を削除」の確認画面 |

## 参考資料

- [SHA-2（Wikipedia）](https://en.wikipedia.org/wiki/SHA-2)：SHA-256
- [Kind of Like That（The Hacker Factor Blog）](https://www.hackerfactor.com/blog/index.php?/archives/529-Kind-of-Like-That.html)：dHashの解説
- [Hamming distance（Wikipedia）](https://en.wikipedia.org/wiki/Hamming_distance)：ハミング距離
- [BK-tree（Wikipedia）](https://en.wikipedia.org/wiki/BK-tree)：BK木
- [Disjoint-set data structure（Wikipedia）](https://en.wikipedia.org/wiki/Disjoint-set_data_structure)：Union-Find
