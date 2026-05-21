# はじめに

## インストール

```bash
git clone https://github.com/takyone/spikuit.git
cd spikuit
uv sync --package spikuit-cli
```

## Brainを作る

**Brain**はひとまとまりのナレッジ空間です — Obsidianのvaultやgitリポジトリに近い考え方です。
それぞれのBrainが独自のナレッジグラフ、設定、復習スケジュールを持ちます。
分野やプロジェクトごとに分けて、いくつでも作れます。

`spkt init` で対話ウィザードが立ち上がります:

```
$ spkt init

Brain name [my-project]: math
Configure embeddings? [y/N]: y
  Providers: openai-compat, ollama
  Provider [openai-compat]:
  Base URL [http://localhost:1234/v1]:
  Model [text-embedding-nomic-embed-text-v1.5]:
  Dimension [768]:

--- Summary ---
Brain:    math
Location: /home/user/math/.spikuit/
Embedder: openai-compat
  URL:    http://localhost:1234/v1
  Model:  text-embedding-nomic-embed-text-v1.5
  Dim:    768

Create brain? [Y/n]:

Initialized brain 'math' at /home/user/math/.spikuit/
```

フラグを渡せば非対話で一発初期化もできます:

```bash
spkt init -p openai-compat \
  --base-url http://localhost:1234/v1 \
  --model text-embedding-nomic-embed-text-v1.5
```

作成されるもの:

```
.spikuit/
├── config.toml    # Brain設定
├── circuit.db     # SQLiteデータベース
└── cache/         # エンベディングキャッシュ
```

gitと同じく、`spkt`はカレントディレクトリから親を辿って`.spikuit/`を見つけます。
別のBrainを操作したいときは `--brain <パス>` を指定してください。

## 知識を追加する

```bash
# コンセプトを追加
spkt neuron add "# Functor\n\n圏の間の写像で、構造を保存する。" \
  -t concept -d math

# もう1つ追加
spkt neuron add "# Monad\n\n自己関手の圏におけるモノイド。" \
  -t concept -d math
```

## 概念をつなげる

```bash
# MonadはFunctorの理解が前提
spkt synapse add <monad-id> <functor-id> --type requires

# つながりを確認
spkt neuron inspect <monad-id>
```

## 復習する

```bash
# 復習が必要なNeuronは？
spkt tutor due

# 復習を記録（グレード: miss/weak/fire/strong）
spkt neuron fire <neuron-id> --grade fire

# インタラクティブなクイズセッション
spkt tutor quiz
```

## 検索する

```bash
# グラフ構造を考慮した検索
spkt retrieve "圏論"

# セマンティック検索用のエンベディングを一括生成
spkt embed-all
```

## ソースを取り込む

```bash
# URLから取り込み
spkt source ingest "https://example.com/article" -d cs --json

# ディレクトリごと一括取り込み
spkt source ingest ./papers/ -d cs --json
```

## 可視化

```bash
# インタラクティブなHTMLグラフを生成
spkt visualize
```

## エクスポート

```bash
# フルバックアップ
spkt export -o backup.tar.gz

# QABotバンドル（ポータブルな読み取り専用DB）
spkt export --format qabot -o qa-bundle.db
```

## グレード一覧

| グレード | 意味 |
|---------|------|
| `miss` | 思い出せなかった |
| `weak` | 曖昧 |
| `fire` | 正解 |
| `strong` | 完璧 |

## シナプスタイプ

| タイプ | 方向 | 意味 |
|--------|------|------|
| `requires` | 片方向 | AにはBの理解が必要 |
| `extends` | 片方向 | AはBを拡張する |
| `contrasts` | 双方向 | AとBは対比関係 |
| `relates_to` | 双方向 | 一般的な関連 |
| `summarizes` | 片方向 | コミュニティ要約 → メンバー |
