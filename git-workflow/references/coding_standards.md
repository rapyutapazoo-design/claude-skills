# コーディング規約 — 星空スポット連携 (Next.js / TypeScript)

このプロジェクトは **Next.js App Router + TypeScript** で構築されている。
レビュー時はこの規約と照合すること。

---

## TypeScript

- **`any` 禁止**: 型不明の場合は `unknown` を使い、型ガードで絞り込む
- **型の明示**: 関数の引数・戻り値には必ず型を付ける（推論できる場合は省略可）
- **型定義の集約**: 共有型は `lib/types.ts` に置く。コンポーネントローカルな型はそのファイル内でOK
- **`type` vs `interface`**: 基本は `type`。継承・拡張が必要な場合のみ `interface`
- **非nullアサーション (`!`) の禁止**: `null` チェックを明示的に行う
- **`as` キャストの最小化**: 型ガード関数 (`is` 型述語) や `zod` 等でバリデーションを行う

```typescript
// ❌ 悪い例
const data = response as any;
const value = obj!.property;

// ✅ 良い例
const data: SpotData = response;
if (obj) { const value = obj.property; }
```

---

## React / Next.js

### Server Components vs Client Components
- **デフォルトはServer Component**: インタラクション・ブラウザAPIが不要な場合はServer Componentで書く
- **`"use client"` は最小範囲で**: 末端の小さなコンポーネントにのみ付ける。ページ全体に付けない
- **データフェッチはServer Componentで**: `lib/weather.ts` や `lib/astronomy.ts` はサーバー側で呼ぶ

```typescript
// ✅ 良いパターン: データ取得はServer Component
// app/spots/[id]/page.tsx（Server Component）
const spot = await fetchSpot(id);
return <SpotDetailPanel spot={spot} />; // ClientはUIのみ担当
```

### コンポーネント設計
- **命名**: PascalCase（例: `ScoreBadge`, `SpotDetailPanel`）
- **ファイル名**: コンポーネント名に一致させる（例: `SpotList.tsx`）
- **Props型**: `type SpotListProps = { ... }` の形式で同ファイル内に定義
- **1ファイル1コンポーネント原則**: 小さなサブコンポーネントは別ファイルに切り出す

### Hooks
- **`use` プレフィックス必須**: `useSpotData`, `useAstronomyFilter` など
- **Hooksのルール厳守**: 条件分岐・ループ内でhooksを呼ばない
- **副作用の適切な管理**: `useEffect` の依存配列を正確に指定する

---

## ファイル構成

```
web/
├── app/          # ルーティング（App Router）
│   ├── page.tsx  # トップページ
│   └── spots/[id]/page.tsx
├── components/
│   └── spots/    # スポット関連UI
├── lib/          # ビジネスロジック・API呼び出し
│   ├── types.ts  # 共有型定義
│   ├── weather.ts
│   ├── astronomy.ts
│   ├── scoring.ts
│   └── distance.ts
└── public/       # 静的ファイル
```

- `lib/` にUIコードを書かない
- `components/` にAPIコール・複雑なロジックを書かない

---

## インポート順序

```typescript
// 1. Reactコア
import { useState, useEffect } from "react";
// 2. Next.js
import Link from "next/link";
import Image from "next/image";
// 3. 外部ライブラリ（あれば）
// 4. 内部 lib/
import { fetchSpots } from "@/lib/scoring";
import type { Spot } from "@/lib/types";
// 5. 内部 components/
import { ScoreBadge } from "@/components/spots/ScoreBadge";
// 6. スタイル
import styles from "./page.module.css";
```

---

## その他

- **コンソールログ**: `console.log` を本番コードに残さない（デバッグ用は `console.error` または削除）
- **エラーハンドリング**: 外部API（天気・天文データ）の呼び出しは必ず `try/catch` で囲む
- **コメント**: 実装意図が分かりにくい箇所には日本語コメントを書く。型定義・関数名は英語
- **マジックナンバー禁止**: 意味のある数値は定数に切り出して命名する

```typescript
// ❌ 悪い例
if (score > 0.7) { ... }

// ✅ 良い例
const GOOD_SEEING_THRESHOLD = 0.7;
if (score > GOOD_SEEING_THRESHOLD) { ... }
```
