# セキュリティレビュールール

プッシュ前に必ず確認するセキュリティ・品質チェック項目。

---

## 🔴 シークレット漏洩チェック（必須）

以下のパターンがコード内にハードコードされていないか確認する。

### APIキー・トークン
- AWS: `AKIA[0-9A-Z]{16}` 形式のアクセスキー
- GCP: `AIza[0-9A-Za-z\-_]{35}` 形式のAPIキー
- GitHub: `ghp_[0-9a-zA-Z]{36}` / `gho_` / `ghs_` / `ghr_` 形式のトークン
- Slack: `xox[baprs]-` で始まるトークン
- Stripe: `sk_live_` / `pk_live_` で始まるキー
- 汎用パターン: `secret`, `api_key`, `apikey`, `password`, `passwd`, `token` などのキー名に値が代入されている箇所

### 接続文字列
- データベースURL: `postgresql://`, `mysql://`, `mongodb://` + 認証情報を含むもの
- `://user:password@` 形式

---

## 🔴 除外ファイルチェック（必須）

以下のファイルがステージングに含まれていないか確認する。

- `.env` / `.env.local` / `.env.production` など環境変数ファイル
- `node_modules/` ディレクトリ
- `*.log` ログファイル
- `.DS_Store`
- `*.pem` / `*.key` / `*.p12` 秘密鍵ファイル
- `credentials.json` / `service-account.json`

---

## 🟡 コード品質チェック（推奨）

- `TODO` / `FIXME` / `HACK` コメントが新たに追加されていないか
- `console.log` / `print` / `debugger` などのデバッグ文が残っていないか
- 外部API呼び出しに `try/catch` が実装されているか
- エラーが握りつぶされていないか（`except: pass` / `catch(e) {}` など）

---

## 🟡 公開リスクチェック（推奨）

- 内部URLやIPアドレスがハードコードされていないか（`192.168.`, `10.0.`, `localhost` を本番コードに含む場合）
- コメントに機密情報・社内情報が含まれていないか
- 個人情報（メールアドレス・電話番号・氏名）がテストデータとして残っていないか
