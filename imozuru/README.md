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
- `.gitignore`（本家のもの）

## 本家からの変更点

`SKILL.md` 内の主な追加箇所には「このリポジトリでの追加」と印を付けました。印の無い改変も含む一覧は下のとおりです。

- **SKILL.md の frontmatter**: description を全面的に書き換え、起動語を「芋づる式に検索してください」（文字どおり含む場合のみ）に限定、`model: haiku` を追加
- **SKILL.md 冒頭**: 出典（MaryCache/imozuru・MIT・コミット 14635fb）を示す行を追加
- **モデル方針の節（追加）**: Haiku 基準、Sonnet への昇格条件1〜5、昇格は最大3回/調査、Opus は使わない、昇格を `log.md` に記録
- **進捗表示の節（追加）**: `🍠 芋づるモード | 手順N`、`✅ 芋づる検索完了`、`⬆️ Sonnet へ昇格（条件N）`
- **watch モード**: 起動語を「芋づる式に検索してください（見張り：<話題>）」に切り替え。見張り先の `watch.py add` は候補を示してユーザーの承認を得てから行う（承認制）
- **検索役の型とツール制限**: 書き込みの道具を持たない型（`Explore` など）を選び、頼み方に書き込み・Bash・ダウンロード禁止を明記
- **watch モードの挙動**: `~/research/<話題>/` が無ければ、先に通常の調査を勧めて終了する、を追加
- **`watch/` のファイル名**: SKILL.md 内の `watch/<日付>.md` の表記を `watch/<日付-時刻>.md` に修正（本家内の表記揺れ。`watch.py` の実際の出力名に合わせた。scripts は変更しておらず、`watch.py` の docstring には本家どおり `watch/<日付>.md` が残る）
- **スクリプトの呼び出しパス**: `~/.claude/skills/imozuru/scripts/` 基準に変更
- **examples/demo の参照**: `tests/fixtures/demo` に変更
- **`scripts/fetch.py` / `scripts/watch.py`**: `safe_url()` を追加。渡す URL と転送先を http/https に限定（`file://`、`-` で始まる文字列、空白・改行を含むもの）。`fetch.py` は `FAIL` で拒否。`watch.py` は `ValueError` / `HTTPError` で取得を拒否し、`add` は「足せなかった」と出して終わり、`check` はそのフィードを「取れなかった」と記して飛ばし他のフィードは見る。`yt-dlp` には URL の前に `--` を挟む
- **`scripts/fetch.py` の OCR**: `ocr_langs()` を追加。tesseract に日本語データ（jpn）があれば英語+日本語（`-l eng+jpn`）、無ければ（確認に失敗しても）従来どおり英語だけ（`-l eng`）で動かす。`tests/test_ocr_langs.py` を追加
- **tests**: 配置に合わせてパスを調整。`tests/test_url_safety.py` と `tests/test_ocr_langs.py` を追加

## 理論・研究の出典

SKILL.md の各決まりがどの文献のどこから来たかは [`references/theory.md`](./references/theory.md) の「決まりと出典」の表にまとまっています。表に載る主な文献:

- Bates 1989「The design of browsing and berrypicking techniques for the online search interface」
- Kuhlthau 1991「Inside the Search Process」
- Ellis 1987 博士論文（探索行動モデル）
- Zhou ら 2026「Explore Before Committing」（HypoSearch、arXiv 2609.01294）
- Roh & Han 2026「HALT」（止めどきの根拠、arXiv 2608.02009）
- Zhang ら 2026「To Search or Not to Search」（arXiv 2602.03304）
- Kastner ら 2007「Estimating the Horizon of Articles to Decide When to Stop Searching」
- 横井祥 2017「Examine the meaning of unknown terms」（Speaker Deck）
- Pirolli & Card 1999「Information foraging」（表に載るが**未取得**・本体は有料）

`theory.md` に「まだ読んでいない定番（届いたら足す）」として挙がっているもの（出典としては使っていない）: Marchionini 2006「Exploratory search」、Case & Given 2016、Wilson 1999、Booth 2010、TARCiS 2024。

## 外部サービス・外部コマンド

- **OpenAlex API**: `scripts/chain.py` が引用・著者をたどるために使う（無料枠、API キーや支払いの登録はしない）
- 任意の外部コマンド（無ければ該当処理が `FAIL` する）:
  - `pdftotext`（PDF の文字取り出し）
  - `pdftoppm` と `tesseract`（文字の層が無い PDF の OCR。日本語の OCR には tesseract の日本語データ（jpn。Homebrew なら `brew install tesseract-lang`）が要る。無ければ英語だけ読む）
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

実行後は `find imozuru -name __pycache__ -prune -exec rm -rf {} +` で `__pycache__` を消します。
