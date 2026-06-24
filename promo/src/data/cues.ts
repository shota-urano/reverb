// 実データの形（Swift: SubtitleCue / 09-data-model §3.4）に合わせたサンプル。
// 内容は実際に Reverb で処理した NASA クリップ（p_3cc93709…）の冒頭ペアを使用し、
// アプリシーン（同クリップの実再生）と筋が通るようにしている。

export type SubtitleCue = {
  id: number;
  start: number; // 元動画時間軸の秒
  end: number;
  lines: string[]; // そのまま描画（UI 側で再分割しない）
};

// 元動画（英語ナレーション）の字幕。Reverb 適用「前」。
// 実 transcript: "there is no stopping what comes next."
export const sourceCue: SubtitleCue = {
  id: 0,
  start: 0,
  end: 2.2,
  lines: ["There is no stopping", "what comes next."],
};

// Reverb が出力した日本語字幕。適用「後」。実 subtitles.json の cue 0。
export const reverbCue: SubtitleCue = {
  id: 0,
  start: 0,
  end: 2.2,
  lines: ["次に来るものは、", "止められない。"],
};
