// 実データの形（Swift: SubtitleCue / 09-data-model §3.4）に合わせたサンプル。
// 日本語 cue は「最大2行・各行 全角20字前後」の確定仕様どおり（ルール4）。
// 作り物感をなくすため、本番では実際の subtitles.json をそのまま読み込む。

export type SubtitleCue = {
  id: number;
  start: number; // 元動画時間軸の秒
  end: number;
  lines: string[]; // そのまま描画（UI 側で再分割しない）
};

// 元動画（英語・講義/解説）の字幕。Reverb 適用「前」。
export const sourceCue: SubtitleCue = {
  id: 12,
  start: 0,
  end: 5,
  lines: [
    "The key idea is that attention lets",
    "the model focus on relevant tokens.",
  ],
};

// Reverb が出力した日本語字幕。適用「後」。
export const reverbCue: SubtitleCue = {
  id: 12,
  start: 0,
  end: 5,
  lines: ["ここで重要なのは、注意機構が", "関連する語に集中できる点です"],
};
