# imozuru

知らない分野を、引用・リンク・著者を芋づる式にたどって原文まで掘るリサーチスキル。原文を要約せずそのまま `~/research/<話題>/` に保存します。

このスキルは外部 OSS **MaryCache/imozuru** をカスタマイズして取り込んだものです。以下に出典と変更点を明記します。

---

## 出典

- 出典リポジトリ: [MaryCache/imozuru](https://github.com/MaryCache/imozuru)
- 取り込み元コミット: `14635fb74a1f68e5c138379c3a6e4ec823b7cb59`
- ライセンス: MIT（Copyright (c) 2026 MaryCache）。全文は [`LICENSE`](./LICENSE) を参照

## 取り込み範囲

取り込んだもの:

- `SKILL.md`
- `references/theory.md`
- `scripts/`（`fetch.py` / `chain.py` / `report.py` / `watch.py`）
- `tests/`
- `LICENSE`

取り込まなかったもの:

- `assets/brand`
- `examples`（デモのみ、最小限を `tests/fixtures/demo` にコピー）
- `README.md` / `README.en.md`（本家のもの。このファイルは本リポジトリ用に新規作成）

## 本家からの変更点

`SKILL.md` 内で「このリポジトリでの追加」と印を付けた箇所が、本リポジトリでの改変・追加箇所です。

- **SKILL.md の frontmatter**: 起動語を「芋づる式に検索してください」（文字どおり含む場合のみ）に限定、`model: haiku` を追加
- **モデル方針の節（追加）**: Haiku 基準、Sonnet への昇格条件1〜5、昇格は最大3回/調査、Opus は使わない、昇格を `log.md` に記録
- **進捗表示の節（追加）**: `🍠 芋づるモード | 手順N`、`✅ 芋づる検索完了`、`⬆️ Sonnet へ昇格（条件N）`
- **watch モード**: 起動語を「芋づる式に検索してください（見張り：<話題>）」に切り替え。見張り先の `watch.py add` は候補を示してユーザーの承認を得てから行う（承認制）
- **検索役の型とツール制限**: 書き込みの道具を持たない型（`Explore` など）を選び、頼み方に書き込み・Bash・ダウンロード禁止を明記
- **スクリプトの呼び出しパス**: `~/.claude/skills/imozuru/scripts/` 基準に変更
- **examples/demo の参照**: `tests/fixtures/demo` に変更
- **`scripts/fetch.py` / `scripts/watch.py`**: `safe_url()` を追加。渡す URL と転送先を http/https に限定（`file://`、`-` で始まる文字列、空白・改行を含むものは `FAIL`）。`yt-dlp` には URL の前に `--` を挟む
- **tests**: 配置に合わせてパスを調整。`tests/test_url_safety.py` を追加

## 理論・研究の出典

SKILL.md の各決まりがどの文献のどこから来たかは [`references/theory.md`](./references/theory.md) にまとまっています。主な文献:

- Bates 1989「The design of browsing and berrypicking techniques for the online search interface」
- Kuhlthau 1991「Inside the Search Process」
- Ellis 1987 博士論文（探索行動モデル）
- Pirolli & Card 1999「Information foraging」
- Marchionini 2006「Exploratory search」

## 外部サービス・外部コマンド

- **OpenAlex API**: `scripts/chain.py` が引用・著者をたどるために使う（無料枠、API キーや支払いの登録はしない）
- 任意の外部コマンド（無ければ該当処理が `FAIL` する）:
  - `pdftotext`（PDF の文字取り出し）
  - `pdftoppm` と `tesseract`（文字の層が無い PDF の OCR）
  - `yt-dlp`（YouTube の字幕）
  - `ax`（https://github.com/yusukebe/ax ・HTML の本文取り出し。無ければ標準ライブラリで代替）

検索語として問いの中身が外部に出るため、機密・個人データが絡む調べものには使わないでください。

## 配置

**配置先は `~/.claude/skills/imozuru/` 固定**です（SKILL.md がスクリプトをこのパスで呼ぶため、プロジェクト単位では配置できません）。

## テスト

リポジトリルートで実行します。

```
python3 -I -m unittest discover -s imozuru/tests
```
