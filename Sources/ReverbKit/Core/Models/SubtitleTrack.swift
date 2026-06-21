import Foundation

/// 字幕トラック（`subtitles.json` / 09-data-model §3.4）。
///
/// バックエンドが整形した cue 列を**そのまま**保持する。UI 側で再分割・再折り返しはしない
/// （ルール3 / 05 §5）。プレーヤーは現在時刻に該当する cue を選ぶだけで、文面は加工しない。
public struct SubtitleTrack: Codable, Sendable, Equatable {
    public let version: Int
    public let cues: [SubtitleCue]

    public init(version: Int, cues: [SubtitleCue]) {
        self.version = version
        self.cues = cues
    }

    /// 現在再生時刻に該当する cue を返す（半開区間 `[start, end)` / 09 §2・05 §3.2）。
    ///
    /// cue は時間的に重ならず昇順である前提（05 §3.2）。先頭から線形に探す
    /// （字幕数は高々数千で、表示は毎フレームではなく時刻変化時のみ呼ぶため十分速い）。
    /// 該当無し（cue 間の無音区間など）は nil＝非表示。
    public func cue(at time: Double) -> SubtitleCue? {
        guard time.isFinite else { return nil }
        return cues.first { $0.start <= time && time < $0.end }
    }
}

/// 字幕キュー1件（09-data-model §3.4 の `cues[]` 要素）。
public struct SubtitleCue: Codable, Sendable, Equatable, Identifiable {
    /// cue 連番（0 始まり。`tts/cue_%04d.wav` のインデックスと一致）。
    public let id: Int
    /// 表示区間の開始（元動画時間軸の秒）。
    public let start: Double
    /// 表示区間の終了（元動画時間軸の秒）。
    public let end: Double
    /// 表示行（最大2行 / 各行 全角20字前後）。そのまま描画する。
    public let lines: [String]
    /// 由来翻訳セグメント id（トレーサビリティ用・任意）。表示には使わない。
    public let segmentIds: [Int]?

    public init(id: Int, start: Double, end: Double, lines: [String], segmentIds: [Int]? = nil) {
        self.id = id
        self.start = start
        self.end = end
        self.lines = lines
        self.segmentIds = segmentIds
    }
}
