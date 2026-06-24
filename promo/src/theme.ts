// Reverb のデザイントークンをミラー（Swift: ReverbTheme / design-system §2-4）。
// プロモ②と App Store プレビュー①のオーバーレイで共用する単一情報源。
export const theme = {
  // アクセント Indigo 基準 #4F63E9（選択/進捗/主要操作に限定）。
  accent: "#4F63E9",
  // 動画面（黒〜チャコール）。
  videoSurface: "#0E0E11",
  // 字幕背景帯（黒 72%）。
  subtitleScrim: "rgba(0,0,0,0.72)",
  // 文字色。
  textPrimary: "#FFFFFF",
  textMuted: "rgba(255,255,255,0.62)",
  // 形状（角丸）。
  radiusPlayer: 13,
  radiusBadge: 9,
  // プレーヤーのアスペクト比 16:9。
  videoAspectRatio: 16 / 9,
  // 日本語が headless Chromium でも出るようフォントスタックを明示。
  // ※レンダリング配布時は Noto Sans JP の埋め込みを検討（@remotion/google-fonts）。
  fontJa: "'Hiragino Sans', 'Noto Sans JP', sans-serif",
} as const;
