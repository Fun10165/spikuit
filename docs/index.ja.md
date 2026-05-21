# Spikuit

**会話で育てるナレッジグラフ**

> *前処理も、チャンキングパイプラインも、メタデータ設計も要らない。
> ドキュメントを放り込んで、エージェントと話すだけ。*

---

Spikuit（spike + circuit、読み: /spaɪ.kɪt/）は、ナレッジ管理で一番面倒な
取り込み・構造化・メンテナンスを、AIエージェントとの会話だけで回せる
パーソナルナレッジシステムです。

従来のRAGはデータ整備で行き詰まります。チャンキング、タグ付け、
関連付け、鮮度管理 — どれも地味に手間がかかる。Spikuitは
**Conversational Curation**（対話型キュレーション）でこの問題を解きます。
会話するだけでナレッジベースが育っていきます。

## クイックスタート

### 1. インストール

```bash
pip install spikuit
```

### 2. Brainを作る

BrainはSpikuitのワークスペースです。`.git/`と同じような感覚で、
知識を管理したい場所で `spkt init` を実行します。

```bash
mkdir my-brain && cd my-brain
spkt init
```

対話ウィザードでエンベディングの設定を聞かれます。
まず試すだけなら「none」でOK — あとからいつでも変更できます。

### 3. 知識を入れてみる

```bash
# コンセプトを追加
spkt neuron add "# Rustの所有権\n\n値には所有者がひとりだけ。スコープを抜けると値は破棄される。" \
  -t concept -d rust

# URLからまとめて取り込み
spkt source ingest "https://doc.rust-lang.org/book/ch04-01-what-is-ownership.html" -d rust

# 関連するNeuron同士をつなげる
spkt synapse add <id-1> <id-2> -t relates_to
```

### 4. Agent CLIのスキルをセットアップ（おすすめ）

チュータリング、ナレッジキュレーション、Q&Aなどの対話型スキルは、
[Claude Code](https://docs.anthropic.com/en/docs/claude-code)、
Cursor、Codexといった**Agent CLI** の上で動きます。
使うには、スキル定義をインストールしてください。

```bash
spkt skills install                    # デフォルトは .claude/skills/
spkt skills install -t .cursor/skills  # 他のAgentを使う場合
```

スキルファイル（`SKILL.md`）と、エージェント向けのコマンドリファレンス
（`SPIKUIT.md`）がコピーされます。

### 5. 使い始める

**Agent CLIから：**

```
You: /spkt-ingest
     圏論を勉強中。FunctorとMonadの定義をBrainに入れて。

Agent: 2個のNeuronを追加、1本のSynapse（Monad --requires--> Functor）を作成。

You: /spkt-qabot
     FunctorとMonadの関係は？

Agent: MonadはFunctorの上に成り立つ構造で...
       ソース: n-abc123 (Functor), n-def456 (Monad)

You: /spkt-tutor

Tutor: まずFunctorから — Monadの前提になっています。
       [教える → クイズ → フィードバック → 弱い部分を再説明]

You: /spkt-curator

Curator: "math"ドメインが2つのコミュニティにまたがっています（代数 vs 解析）。
         サブドメインに分割しますか？ [Y/n]
```

**`spkt` コマンドを直接使うこともできます：**

```bash
spkt retrieve "所有権 借用"                   # ナレッジグラフを検索
spkt tutor due                              # 復習が必要なNeuronは？
spkt neuron fire <id> -g fire               # 復習を記録
spkt diagnose                               # Brainの健全性チェック
spkt consolidate                            # グラフ構造を最適化
spkt visualize                              # インタラクティブなHTMLグラフ
```

全コマンドで `--json` が使えます。

## 3つのスキル + キュレーター

### `/spkt-ingest` — 話して取り込む

記事でもメモでもURL でも、Brainに投げるだけ。エージェントが中身を分割して
関連を見つけ出し、グラフを組み立てます。

```
You: /spkt-ingest
     この論文をBrainにまとめて: https://arxiv.org/abs/1706.03762

Agent: 8個のNeuronを追加（Multi-Head Attention, Scaled Dot-Product, ...）。
       6本のSynapseを作成、引用元としてSourceを紐付け。
```

### `/spkt-qabot` — 聞いて引き出す

Brainに自然言語で質問すると、ソース付きで答えが返ってきます。
使い続けるほど検索の質が上がります — 的外れな結果は自動でペナルティ、
役に立った結果はブーストされます。

```
You: /spkt-qabot
     Multi-Head Attentionとシングルヘッドの違いは？

Agent: Multi-Head Attentionは複数のAttention関数を並列実行し...
       ソース:
       - [Attention Is All You Need](https://arxiv.org/abs/1706.03762)
```

### `/spkt-tutor` — 任せて学ぶ

ナレッジグラフの上に乗ったAIチューター。前提知識を把握して、
難易度を自動調整し、間違えたら「正解/不正解」で終わらせず
ちゃんとフィードバックを返します。

```
You: /spkt-tutor

Tutor: まずFunctorから始めましょう — 他の2つの前提になっています。
       [教える → クイズ → フィードバック → 弱い部分を再説明]
```

### `/spkt-curator` — 会話でメンテナンス

ドメインとコミュニティのズレを分析して、ラベルの修正、
孤立Neuronの接続、弱いSynapseの整理を会話ベースで進めます。

```
You: /spkt-curator

Curator: "math"ドメインが代数と解析で2つに割れています。
         "math-algebra"と"math-analysis"に分けますか？
```

## 仕組み

1. **理解度に応じたスケジューリング** — Neuronごとに復習タイミングを最適化
   （[FSRS](https://github.com/open-spaced-repetition/fsrs4anki)）
2. **活性化の伝播** — ひとつ復習すると、つながっている知識の復習時期も近づく。
   よく一緒に使う接続ほど強くなる。
3. **検索の自動改善** — 関連度 × 記憶の強さ × グラフ中心性でランキング。
   フィードバックで精度が上がり続ける。

## ドキュメント

- [はじめに](getting-started.ja.md) — インストール、初期化、最初のコマンド
- [使い方](how-to-use.ja.md) — ユースケース、エージェントスキル、Python API
- [コンセプト](concepts.ja.md) — Brain、グラフモデル、つながりの仕組み
- [CLIリファレンス](cli.ja.md) — 全`spkt`コマンド
- [Appendix](appendix/index.md) — アルゴリズムと技術的詳細
- [APIリファレンス](reference/index.md) — Python APIドキュメント

## ライセンス

Apache-2.0
