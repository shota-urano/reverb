# Reverb プロモ動画（Remotion）

Reverb のマーケ用プロモ動画を **Remotion**（React/TypeScript でコードから動画生成）で作る。
共通コンポーネント（字幕パタッ替え／波形の主従／工程チップ）は **App Store プレビューのオーバーレイにも流用**する想定。

> アプリ本体の「ローカル完結」ルールはマーケ素材生成には適用しない。ただし動画の主張（クラウドに送らない）と矛盾する演出はしない。

## セットアップ

```sh
cd promo
npm install
```

## コマンド

| 用途 | コマンド |
|------|----------|
| 編集プレビュー（Remotion Studio） | `npm run dev` |
| 本編を書き出し（→ `out/reverb-promo.mp4`） | `npm run render` |
| 核カットだけ書き出し | `npm run render:swap` |

## 構成（約14.5秒・1080p / 30fps）

`src/Promo.tsx` が本編。4シーンを `Series` で連結し、各シーンは内部で fade in/out する。

| シーン | 尺 | ファイル |
|--------|----|----------|
| つかみ（課題提示） | 2.5s | `src/scenes/HookScene.tsx` |
| 字幕入替（核） | 5.0s | `src/SubtitleSwap.tsx` |
| 仕組み（6工程チップ） | 4.0s | `src/scenes/PipelineScene.tsx` |
| 締め（ロゴ） | 3.0s | `src/scenes/OutroScene.tsx` |

- `src/theme.ts` … アプリのデザイントークン（`ReverbTheme`）をミラー。アクセント `#4F63E9`／字幕帯 黒72%／16:9。
- `src/data/cues.ts` … 字幕は実データの形（`SubtitleCue`: id/start/end/lines、最大2行・全角20字前後）に準拠。本番は実際の `subtitles.json` を読み込む。
- 工程名は Swift `StageName.displayName`（音声抽出→文字起こし→翻訳→字幕整形→音声合成→ミックス）と一致。

## TODO（仕上げ）

- [ ] BGM＋日本語ナレーション＋効果音（`<Audio>`）
- [ ] 配布フォーマット（正方形 1080×1080 / 縦 1080×1920）の Composition 追加
- [ ] Noto Sans JP 埋め込み（配布レンダリング機での日本語フォント担保。現状は macOS Hiragino 依存）
- [ ] ① App Store プレビュー：アプリ実機キャプチャ＋共通部品オーバーレイ
