# 超解像（Lanczos3による拡大）

「⋯ → 超解像を適用」は、表示中の画像を1.5・2・3・4倍に拡大します。**拡大には機械学習を使わず、Lanczos3という補間（リサンプリング）を使います。** 一般に「超解像」と呼ばれる、学習済みモデルで細部を描き足す方法とは違います。

## 仕組み

拡大した画像の各画素は、元の画像の近くにある画素の重み付き平均で決めます。重みを決める関数（窓付きsinc関数）は次のとおりです。

```text
L(x) = sinc(x) · sinc(x / 3)    （-3 < x < 3）
L(x) = 0                        （それ以外）
sinc(x) = sin(πx) / (πx)
```

- 「3」は窓の幅で、Lanczos3の名前の由来です。拡大では、縦横それぞれ前後3画素ずつ（1方向に6画素）を使います。
- 計算は横方向と縦方向に分けて行います。重みの合計は1になるように調整します。
- 単純な方法（最近傍・双線形）に比べて輪郭がぼやけにくい一方、くっきりした輪郭の周りにわずかな縁取り（リンギング）が出ることがあります。計算結果は0〜255の範囲に収めます。

透過のある画像では、色に透明度を掛けた形（乗算済みアルファ）にしてから拡大し、元に戻します。こうしないと、完全に透明な部分に残っている色が、見えている部分の輪郭ににじみ出ます。

## 機械学習による超解像との違い

| | Sumīreの超解像（Lanczos3） | 機械学習による超解像（Real-ESRGAN・waifu2xなど） |
| --- | --- | --- |
| 細部 | 元の画素から計算するだけで、新しい細部は生まれない | 学習した内容から、もっともらしい細部を描き足す |
| 隠した部分 | モザイクはモザイクのまま拡大される | モザイクの境目を滑らかにしたり、形を描き足したりすることがある |
| 結果 | 同じ入力からは常に同じ結果 | モデルや設定で結果が変わる |
| 配布・動作 | 追加のモデルが要らず、CPUですぐ終わる | モデルの同梱（大きさ・ライセンス）と、多くの計算が必要 |

Sumīreは画像の一部を隠すためのアプリなので、**隠した部分に情報を描き足さない**ことを優先してLanczos3を選んでいます。拡大しても、モザイクやぼかしで隠した部分が復元されることはありません。

## ほかに使っている場所

同じ処理（[`lanczos3_resize`](../../sumire/editing.py)）を、次の場面でも使います。縮小のときは、縮小の比率に合わせて参照する範囲を広げ、細かい模様のちらつき（エイリアシング）を抑えます。

- 切り抜き画面の「出力の寸法を指定する（拡大・縮小）」
- 形式変換・容量削減の「長辺の上限」
- コラージュでの画像の大きさの調整

加工の範囲を記録したマスクは、白黒の区別を保つため、拡大・縮小に最近傍法を使います。

## 制限

- 拡大後の寸法は、1辺32,768px・合計2,400万画素までです。これを超える倍率は選べません。
- 拡大は画像全体に対して行い、保存方法の設定に従って保存します。「元に戻す」で取り消せます。

## 該当するコード

| 場所 | 内容 |
| --- | --- |
| [`sumire/editing.py`](../../sumire/editing.py) | `lanczos3_resize`（乗算済みアルファでの補間）、`upscaled_size`（倍率と上限の確認）、`upscale_lanczos3` |
| [`sumire/output_dialogs.py`](../../sumire/output_dialogs.py) | 「超解像を適用」の画面（`UpscaleDialog`） |
| [`sumire/output_features.py`](../../sumire/output_features.py) | 表示中の画像への適用（`upscale_image`） |

補間そのものは[Pillow](https://python-pillow.org/)の `Image.Resampling.LANCZOS` が行います。Pillowの実装では、窓の幅は3です（`src/libImaging/Resample.c` の `lanczos_filter`）。

## 参考資料

- [Lanczos resampling（Wikipedia）](https://en.wikipedia.org/wiki/Lanczos_resampling)：Lanczos補間の定義と性質
- [Pillow：Filters](https://pillow.readthedocs.io/en/stable/handbook/concepts.html#filters)：Pillowの補間方法の一覧と比較
- [Pillow：Resample.c](https://github.com/python-pillow/Pillow/blob/main/src/libImaging/Resample.c)：Lanczos3の実装
- [Alpha compositing（Wikipedia）](https://en.wikipedia.org/wiki/Alpha_compositing)：乗算済みアルファ
- [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN)（[論文](https://arxiv.org/abs/2107.10833)）、[waifu2x](https://github.com/nagadomi/waifu2x)：機械学習による超解像の例（Sumīreでは使っていません）
