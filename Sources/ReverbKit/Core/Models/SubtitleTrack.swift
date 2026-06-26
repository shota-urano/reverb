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

    /// 現在再生時刻に該当する cue を返す（半開区間 `[displayStart, displayEnd)` / 09 §2・05 §3.2）。
    ///
    /// 表示区間は cue の `displayStart`/`displayEnd`＝**音声の実配置時刻**（`audioStart`/`audioEnd`）が
    /// あればそれ、無ければ元の `start`/`end`。吹き替え音声は尺合わせの押し出しで元字幕時刻から
    /// ドリフトするため、音声配置時刻に合わせて表示することで「聞こえる日本語」と字幕を一致させる。
    ///
    /// cue は時間的に重ならず昇順である前提（05 §3.2）。先頭から線形に探す
    /// （字幕数は高々数千で、表示は毎フレームではなく時刻変化時のみ呼ぶため十分速い）。
    /// 該当無し（cue 間の無音区間など）は nil＝非表示。
    public func cue(at time: Double) -> SubtitleCue? {
        guard time.isFinite else { return nil }
        return cues.first { $0.displayStart <= time && time < $0.displayEnd }
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
    /// 吹き替え音声の実配置開始（秒・任意）。mix が尺合わせ後の placement を書き込む。
    /// 在れば表示同期に使う。音声未配置の cue（TTS skip 等）では nil。
    public let audioStart: Double?
    /// 吹き替え音声の実配置終了（秒・任意）。`audioStart` と対で書かれる。
    public let audioEnd: Double?

    /// 表示開始＝音声配置時刻があればそれ、無ければ元字幕時刻。
    public var displayStart: Double { audioStart ?? start }
    /// 表示終了＝音声配置時刻があればそれ、無ければ元字幕時刻。
    public var displayEnd: Double { audioEnd ?? end }

    public init(
        id: Int,
        start: Double,
        end: Double,
        lines: [String],
        segmentIds: [Int]? = nil,
        audioStart: Double? = nil,
        audioEnd: Double? = nil
    ) {
        self.id = id
        self.start = start
        self.end = end
        self.lines = lines
        self.segmentIds = segmentIds
        self.audioStart = audioStart
        self.audioEnd = audioEnd
    }
}
