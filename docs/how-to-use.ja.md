# 使い方

ユースケース別のガイドです。コマンド一覧は[CLIリファレンス](cli.ja.md)、
Python APIの詳細は[APIリファレンス](reference/index.md)を参照。

## CLIレシピ

### 知識の追加

```bash
# シンプルなコンセプト
spkt neuron add "# Functor\n\n圏の間の構造を保つ写像。" -t concept -d math

# フロントマター付き
spkt neuron add "---
type: concept
domain: french
---
# Subjonctif
疑い、感情、必要性を表すときに使う。"

# ファイルから
cat notes.md | spkt neuron add -t note -d physics
```

### 概念をつなげる

```bash
# 「MonadにはFunctorの理解が必要」
spkt synapse add <monad-id> <functor-id> -t requires

# 「HTTPとgRPCは対比関係」（双方向にエッジが張られる）
spkt synapse add <http-id> <grpc-id> -t contrasts
```

### 復習する

```bash
# 期限が来ているものは？
spkt tutor due

# インタラクティブなフラッシュカードセッション（Textual TUI）
# キー: Space=めくる, 1-4=成績, n=ノート, q=終了
spkt tutor quiz

# エージェント向け: 期限到来カードを一括JSON出力
spkt tutor quiz --json

# 手動で復習を記録（外部で復習した場合など）
spkt neuron fire <neuron-id> -g fire
```

### 検索・探索

```bash
# グラフ構造を考慮した検索（キーワード + セマンティック + 記憶の強さ + 中心性）
spkt retrieve "functor"

# タイプやドメインで絞り込み
spkt neuron list -t concept -d math

# Neuronの詳細を見る（復習状態、隣接ノード）
spkt neuron inspect <neuron-id>

# 統計
spkt stats
```

### ディレクトリの一括取り込み

```bash
# テキストファイルをまとめて取り込み
spkt source ingest ./papers/ -d cs --json

# metadata.jsonlでメタデータを付与
echo '{"file_name": "paper1.md", "filterable": {"year": "2024"}, "searchable": {"abstract": "..."}}' > papers/metadata.jsonl
spkt source ingest ./papers/ -d cs --json
```

### フィルタ付き検索

```bash
# Sourceのメタデータで絞り込み
spkt retrieve "attention mechanism" --filter year=2017

# 複数フィルタの組み合わせ（AND条件）
spkt retrieve "GNN" --filter domain=cs --filter venue=NeurIPS

# 使えるフィルタキーを調べる
spkt neuron list --meta-keys --json
spkt neuron list --meta-values year --json
spkt domain list --json
```

### ソース管理

```bash
# Source一覧
spkt source list --json

# Sourceの詳細（紐づくNeuron含む）
spkt source inspect <source-id> --json

# URLを修正
spkt source update <source-id> --url "https://correct-url.com"

# ドメインのリネーム・統合
spkt domain rename ml machine-learning
spkt domain merge ai ml --into machine-learning
```

### ソースの鮮度管理

```bash
# 古くなったURLソースを再取得
spkt source refresh --stale 30

# 特定のSourceを再取得
spkt source refresh <source-id>
```

### Brainの健全性とメンテナンス

```bash
# 問題を診断（孤立Neuron、弱いSynapse、長期放置など）
spkt diagnose

# ドメインとコミュニティのズレを分析
spkt domain audit

# 学習の進捗レポート
spkt tutor progress
spkt tutor progress --format html -o progress.html

# Brainの中身からユーザーガイドを自動生成
spkt manual

# 睡眠メカニズムに着想を得た統合（まずドライラン→確認してから適用）
spkt consolidate
spkt consolidate apply
```

### エクスポート / インポート

```bash
# フルバックアップ
spkt export -o backup.tar.gz
spkt import backup.tar.gz

# JSON（共有・中身確認用）
spkt export --format json -o brain.json

# QABotバンドル（読み取り専用、エンベディング付き）
spkt export --format qabot -o qa-bundle.db
```

### エクストラクタ

Spikuit はソース形式ごとのプラガブルな取り込みエクストラクタを同梱しています。
`spkt source ingest` は入力に合うエクストラクタへルーティングし、何が
インストールされているか確認できます：

```bash
spkt skills extractor list
spkt skills extractor status              # この環境で動かせるか？
spkt skills extractor show python-code    # 単体のSKILL.md全文
```

v0.6.1 同梱エクストラクタ：

| 名前 | 対応 | 要件 |
|---|---|---|
| `default` | 何でも（フォールバック） | — |
| `python-code` | `*.py`、`pyproject.toml` | `python3` |
| `pdf-paper` | `*.pdf`、`arxiv.org/...` | `pymupdf` |
| `github-repo` | `github.com/...` | `gh` |

ブランド内でシステムエクストラクタをカスタマイズしたい場合は shadcn-style の
copy-to-own で：

```bash
spkt skills extractor fork python-code             # システム版を上書き
spkt skills extractor fork _template my-format     # スケルトンから新規作成
spkt skills extractor refresh
```

ブランド内エクストラクタは `<brain>/.spikuit/extractors/<name>/` に配置され、
名前衝突時はシステム同梱を上書きします。

### バージョン管理とUndo

`spkt init` はBrain内にgitリポジトリを作るので、変更はすべて履歴に残ります。
バッチ取り込みや構造変更の前に短命ブランチを切って、結果を確認してから
`main` にfast-forwardするのが想定運用です（エージェントもこれを守ります）。

```bash
# バッチ取り込み・整理の前にブランチを切る
spkt branch start papers-2026-04        # → ingest/papers-2026-04
spkt source ingest ./papers/ -d math
# ...結果を確認...
spkt branch finish                      # mainにff-merge
spkt branch abandon                     # 気に入らなければブランチごと破棄
```

ブランチの命名規則：

- `ingest/<tag>` — ソースやバッチからの知識追加
- `consolidate/<date>` — 構造的なクリーンアップ（マージ・剪定・consolidate）

コミットメッセージの規約（`spkt history --grep` や `undo --ingest-tag` で
フィルタできます）：

```
ingest(<tag>): N neurons from <source>
consolidate: <要約>
review(<YYYY-MM-DD>): N fired (<correct>/<total>)
manual: <ユーザー記述の要約>
```

履歴確認とロールバック：

```bash
spkt history -n 20                      # 直近のBrainコミット
spkt history --grep ingest              # メッセージでフィルタ
spkt undo                               # HEADをrevert（確認あり）
spkt undo --to <sha>                    # <sha>以降をすべてrevert
spkt undo --ingest-tag papers-2026-04   # タグ付きバッチをrevert
```

`spkt undo` は `git revert` のラッパーなので履歴は書き換えず保存されます。
誤ったundoもまたundoできます。

自分でgit管理したい場合は次のように初期化できます：

```bash
spkt init --no-git
```

### 可視化

```bash
# インタラクティブなHTMLグラフを生成
spkt visualize -o graph.html
```

## エージェントスキル

スキルはLLMを使った対話モードで、
[Claude Code](https://docs.anthropic.com/en/docs/claude-code)
などの**Agent CLI**上で動くよう設計されています。

コアエンジンはLLMなしで完結します — `spkt`コマンドは単独で使えます。
スキルはその上に、チュータリング・キュレーション・Q&Aといった
対話的な機能を乗せるものです。

```
┌──────────────────────────────────────────┐
│  Agent CLI (Claude Code, Codexなど)       │
│  ┌────────────────┐  ┌───────────────┐   │
│  │  LLM推論       │  │  シェルアクセス│   │
│  └───────┬────────┘  └───────┬───────┘   │
│          │   スキル / ツール  │            │
│          └────────┬──────────┘            │
│                   ▼                      │
│        spikuit-core Python API           │
│   (Circuit, Sessions, Learn)             │
│                   │                      │
│              spkt CLI                    │
└──────────────────────────────────────────┘
```

### `/spkt-tutor` — AIチューター

教えて、問い掛けて、コーチする — ただのクイズマシンではない1対1チューターです。

あなたの理解状態を見て、次にやるべきことを判断します。弱い概念を教えたり、
理解度チェックのクイズを出したり、間違いの原因を丁寧に説明したり。

**セッション例：**

```
> /spkt-tutor

Tutor: 5つの概念が復習期限です。Functorは安定性が低く、
       Monadの前提になっているので、こちらから始めましょう。

       [講義] Functorは圏の間の構造を保つ写像です。
       「箱の中身に関数を適用できるもの」と考えると分かりやすいです...
       （あなたが既に知っている概念を使って説明）

       では理解度を確認しますね。

       [クイズ] Functorが写像時に保存するものは何ですか？

You:   圏の構造？

Tutor: [フィードバック] 方向は合っています。もう少し厳密に言うと、
       恒等射と合成を保存します。
       つまり fmap id = id、fmap (f . g) = fmap f . fmap g。

       角度を変えてもう一問。

       [クイズ] Haskellで`fmap`と`map`が別々に存在する理由は？

You:   mapはリスト専用、fmapは任意のFunctorに使える？

Tutor: [フィードバック] その通り！`map`はリスト特化で、
       `fmap`は任意のFunctorインスタンスに使える汎用版です。✅ fire
       安定性: 3.2 → 8.1日

       では今の理解をベースに、Monadに進みましょう...
```

**チューターの行動パターン：**

| 行動 | タイミング | 例 |
|------|----------|-----|
| 診断 | セッション開始時 | 「Functorが弱く、Monadの前提 — ここから」 |
| 講義 | 新規/弱い概念 | 既知の概念を足場にした段階的な説明 |
| クイズ | 講義のあと | 多角的な問い（「〜とは？」だけではない） |
| フィードバック | 回答後 | なぜ正解/不正解か、何が足りなかったか |
| Q&A | 質問されたとき | Brainの知識を使った教育的な回答 |
| ドリル | 弱点が続くとき | 角度を変えた反復練習 |

### `/spkt-ingest` — ナレッジキュレーション

会話しながら知識を追加。エージェントが内容を構造化し、
関連する概念を見つけ、つなげてくれます。

**セッション例：**

```
> /spkt-ingest

何を追加しますか？

> Haskellのモナドはbind (>>=)で計算をつなげる。
  IOとMaybeが代表例。

Neuronを作ります：

── Monad ──
# モナド (Monad)
bind (>>=) で計算を連鎖させる。
例: IO (副作用), Maybe (失敗処理)

関連する概念が2つ見つかりました：
  1. Functor (0.82) → requires
  2. Applicative (0.78) → requires

この接続で作成しますか？ [Y/n]

✅ n-abc123を追加、FunctorとApplicativeにリンク
```

### `/spkt-qabot` — ナレッジQ&A

Brainに質問すると、ソース付きで回答が返ります。
使い続けるほど検索精度が上がっていきます。

**セッション例：**

```
> /spkt-qabot

何でも聞いてください。

> FunctorとApplicativeの違いは？

Functorは包まれた値に関数を適用します（fmap）。
Applicativeはこれを拡張して、包まれた関数を包まれた値に適用できます（<*>）。
ApplicativeはFunctorでもありますが、独立したエフェクトを合成できる点が違います...

ソース: n-abc123 (Functor), n-def456 (Applicative), n-ghi789 (Monad)

> ApplicativeとMonadの関係をもう少し

[前の結果を自動的にペナルティ → 新しい情報を探索]

Over-smoothingはGCNの層を増やすとノード表現が収束する現象で...

ソース: n-jkl012, n-mno345

> ありがとう

✅ ソースをブースト — 今後の検索で優先されます
```

**フィードバックの仕組み：**

- **似たフォローアップ** → 前の結果では足りなかった → ペナルティ
- **感謝やOK** → 役に立った → ブースト
- **話題の転換** → セッションをリセット
- **永続モード** → フィードバックがセッションをまたいで保持

### `/spkt-curator` — 会話でメンテナンス

ドメインとコミュニティのズレを分析して、ラベルの修正、孤立Neuronの接続、
弱いSynapseの整理を会話ベースで進めます。

```
> /spkt-curator

Curator: "math"ドメインが2つのコミュニティにまたがっています:
  c0: 代数、環、体（12 neurons）
  c3: 微積分、極限、導関数（8 neurons）

"math-algebra"と"math-analysis"に分割しますか？ [Y/n]

> y

✅ 8個のNeuronを"math-analysis"にリネーム。

孤立Neuronが3個。"集合論の基礎"を"math-algebra"に接続しますか？ [Y/n]
```

## Python API

独自の統合やエージェント、LLMアダプターを作る場合に。

### Quiz v2 — Flashcard と FreeResponse

```python
from spikuit_core import Circuit, Grade
from spikuit_core.scaffold import compute_scaffold
from spikuit_tutor.quiz import Flashcard, FreeResponseQuiz, QuizResponse

neuron = await circuit.get_neuron("n1")
scaffold = compute_scaffold(circuit, "n1")

# 自己採点 — LLM不要
fc = Flashcard(neuron, scaffold)
result = fc.grade(QuizResponse(self_grade=Grade.FIRE))

# 自由記述 — LLMGrader が必要
fr = FreeResponseQuiz(neuron, scaffold)
raw = fr.grade(QuizResponse(answer="自分の答え"))
assert raw.needs_tutor_grading
```

### TutorSession + ExamPlan

ExamPlan が pedagogy（gap展開・リクエ・elaboration）を宣言的に持ち、
TutorSession はそれを解釈するだけ。

```python
from spikuit_tutor.tutor import plan_exam, TutorSession

plan = await plan_exam(
    circuit,
    neuron_ids=["n1", "n2"],
    elaborate_on_correct=True,
    require_mastery=True,
)
sess = TutorSession(circuit, plan)
step = await sess.teach()
tr = await sess.record_response(QuizResponse(self_grade=Grade.FIRE))
await sess.advance()
```

### LLMGrader（自由記述の採点）

```python
from spikuit_agents.tutor import AgentLLMGrader

async def my_grade_fn(prompt: str) -> str:
    # 任意のLLMバックエンドを呼んでJSONを返す
    return '{"grade": 3, "correctness": 0.8, "feedback": "ok"}'

grader = AgentLLMGrader(my_grade_fn)
final = await grader.grade_free_response(
    question=q, rubric=r, canonical_answer=c, student_response=s,
)
await sess.record_llm_graded(final)
```

### QABotSession

```python
from spikuit_core import QABotSession

session = QABotSession(circuit, persist=True)

# 質問 — スコア付き・重複排除済みの結果が返る
results = await session.ask("Functorとは？")

# 役に立った結果をブースト
await session.accept([results[0].neuron_id])

# フォローアップ — 似た質問なら前の結果を自動ペナルティ
results = await session.ask("Haskellでのfunctorの例は？")

await session.close()  # ブーストをDBに反映
```

### IngestSession

```python
from spikuit_core import IngestSession, SynapseType

session = IngestSession(circuit)

# 知識を追加 — 関連する概念を自動で探してくれる
neuron, related = await session.ingest(
    "# Functor\n\n圏の間の構造を保つ写像。",
    type="concept", domain="math",
)

# つなげる
if related:
    await session.relate(neuron.id, related[0].id, SynapseType.REQUIRES)

# 重複をマージ
await session.merge(["n-old1", "n-old2"], into_id="n-keep")

await session.close()
```
