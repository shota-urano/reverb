import Foundation
import Observation

/// プレーヤー画面のロジック（screens.md §3 / 08 §5）。
///
/// 成果物の取得（`GET /jobs/{id}/result`）、字幕の読込、再生状態（再生位置・音量・字幕ON/OFF）を束ねる。
/// **AVFoundation は持たない**（差し替え不能で単体テストできないため）。View 側の再生コンテナが
/// この VM の「意図」（isPlaying / seek 要求 / 音量）を読み、観測値（現在時刻・尺）を書き戻す。
/// これにより同期再生の配線は View に閉じ、状態遷移・字幕選択・エラー判定はここでテストできる（ルール3）。
@MainActor
@Observable
public final class PlayerViewModel {
    /// 成果物読込のフェーズ。
    public enum LoadPhase: Equatable {
        case loading
        case ready
        case failed(BackendErrorBody)
    }

    // MARK: - 公開状態

    public private(set) var phase: LoadPhase = .loading
    /// 成果物パス（映像・吹き替え音声・字幕・尺）。
    public private(set) var result: JobResult?
    /// 字幕トラック（cue 列）。欠落時は nil＋`subtitleUnavailable`。
    public private(set) var subtitleTrack: SubtitleTrack?

    /// 元動画が移動・削除済み（再選択を促す／成果物は保持・08 §エラー）。
    public private(set) var videoMissing = false
    /// 吹き替え音声が読めない（再生開始せず再処理案内・08 §エラー）。
    public private(set) var voiceoverMissing = false
    /// 字幕のみ欠落（動画・音声は再生し、字幕エラーを明示・08 §エラー）。
    public private(set) var subtitleUnavailable = false

    /// 表示用の翻訳モデル名（`/models` 既定。取得不可なら nil で非表示・ルール6）。
    public private(set) var translateModel: String?

    // MARK: - 再生状態

    /// 再生中か（View の再生コンテナがこの意図に追従する）。
    public private(set) var isPlaying = false
    /// 現在の再生位置（秒・元動画時間軸）。
    public private(set) var currentTime: Double = 0
    /// 全体尺（秒）。初期は成果物 `duration`、再生層がより正確な値を報告したら更新。
    public private(set) var duration: Double = 0
    /// 日本語（主）ゲイン。**確定初期値 100%**（ルール4）。再生中に変更可・再処理ではない。
    public private(set) var japaneseVolume: Double = MixSettings.confirmedInitial.jaVolume
    /// 元音声ゲイン。**確定初期値 8%**（ルール4）。
    public private(set) var originalVolume: Double = MixSettings.confirmedInitial.originalVolume
    /// 字幕表示 ON/OFF。OFF は表示だけを切替え、音声・再生位置に影響させない（08 §字幕）。
    public private(set) var subtitlesEnabled = true
    /// シーク要求トークン。プログラム的シーク時に増やし、再生コンテナが `currentTime` へ追従する。
    public private(set) var seekToken = 0
    /// スライダー操作中。観測時刻の書き戻しでつまみが暴れないよう、この間は時刻更新を無視する。
    public private(set) var isScrubbing = false

    private let jobRepository: (any JobRepository)?
    private let subtitleRepository: any SubtitleRepository
    private let modelRepository: (any ModelRepository)?
    /// 成果物ファイルの存在判定（テスト用に差し替え可能・既定は FileManager）。
    private let fileExists: @Sendable (String) -> Bool

    public init(
        jobRepository: (any JobRepository)?,
        subtitleRepository: any SubtitleRepository = DefaultSubtitleRepository(),
        modelRepository: (any ModelRepository)? = nil,
        fileExists: @escaping @Sendable (String) -> Bool = { FileManager.default.fileExists(atPath: $0) }
    ) {
        self.jobRepository = jobRepository
        self.subtitleRepository = subtitleRepository
        self.modelRepository = modelRepository
        self.fileExists = fileExists
    }

    // MARK: - 派生状態（テスト対象・UI 非依存）

    /// 再生可能か（映像と吹き替え音声がそろっている）。どちらか欠ければ再生を始めない（08 §エラー）。
    public var canPlay: Bool {
        result != nil && !videoMissing && !voiceoverMissing
    }

    /// 現在時刻に表示すべき字幕行（OFF・欠落・該当無しは空）。UI で再分割しない（ルール3）。
    public var currentLines: [String] {
        guard subtitlesEnabled else { return [] }
        return subtitleTrack?.cue(at: currentTime)?.lines ?? []
    }

    /// 再生位置の割合 0.0〜1.0（シークスライダー用）。
    public var progress: Double {
        guard duration > 0 else { return 0 }
        return min(max(currentTime / duration, 0), 1)
    }

    public var currentTimecode: String { ReverbFormat.timecode(currentTime) }
    public var durationTimecode: String { ReverbFormat.timecode(duration) }

    // MARK: - 読込

    /// 成果物を取得し、ファイル健全性・字幕・尺を確定する（screens.md §3 / 08 §5）。
    /// 失敗・再表示のたびに呼び直してよい。
    public func load(jobId: String) async {
        phase = .loading
        await loadTranslateModel()

        guard let jobRepository else {
            phase = .failed(Self.connectionError)
            return
        }

        let result: JobResult
        do {
            result = try await jobRepository.result(id: jobId)
        } catch is CancellationError {
            return
        } catch {
            phase = .failed(Self.errorBody(from: error))
            return
        }

        self.result = result
        duration = max(result.duration, 0)
        videoMissing = !fileExists(result.videoPath)
        voiceoverMissing = !fileExists(result.voiceoverPath)
        await loadSubtitles(path: result.subtitlesPath)
        phase = .ready
    }

    /// 字幕を読む。欠落・破損でも画面全体は失敗にせず、字幕エラーのみ立てる（08 §エラー）。
    private func loadSubtitles(path: String) async {
        subtitleTrack = nil
        subtitleUnavailable = false
        guard fileExists(path) else {
            subtitleUnavailable = true
            return
        }
        do {
            subtitleTrack = try await subtitleRepository.load(path: path)
        } catch is CancellationError {
            // 観測停止。次回 load で取り直す。
        } catch {
            subtitleUnavailable = true
        }
    }

    private func loadTranslateModel() async {
        guard translateModel == nil, let modelRepository else { return }
        translateModel = try? await modelRepository.translationModels().defaultModel
    }

    // MARK: - 再生操作

    /// 再生/一時停止トグル。再生不能（成果物欠落）なら何もしない。
    /// 終端で停止している状態から再生するときは先頭へ巻き戻す（終端のままだと進まないため）。
    public func togglePlayPause() {
        guard canPlay else { return }
        if !isPlaying, duration > 0, currentTime >= duration {
            seek(toTime: 0)
        }
        isPlaying.toggle()
    }

    public func pause() {
        isPlaying = false
    }

    /// 再生位置を割合（0.0〜1.0）でシークする（スライダー確定時など）。
    public func seek(toFraction fraction: Double) {
        guard duration > 0 else { return }
        seek(toTime: fraction * duration)
    }

    /// 再生位置を秒でシークする。映像・吹き替え・元音声・字幕が同時刻へ追従する（08 §5.3）。
    public func seek(toTime time: Double) {
        let clamped = min(max(time, 0), duration)
        currentTime = clamped
        seekToken &+= 1 // 再生コンテナへ「この時刻へ飛べ」を通知。
    }

    /// スライダーのドラッグ開始。以降 `updateObservedTime` を無視し、つまみを操作に委ねる。
    public func beginScrubbing() {
        isScrubbing = true
    }

    /// ドラッグ中のプレビュー（割合）。時刻表示だけ更新し、まだ実シークはしない。
    public func scrub(toFraction fraction: Double) {
        guard duration > 0 else { return }
        currentTime = min(max(fraction * duration, 0), duration)
    }

    /// ドラッグ確定。確定位置へシークしてから観測の受け入れを再開する。
    public func endScrubbing(atFraction fraction: Double) {
        seek(toFraction: fraction)
        isScrubbing = false
    }

    /// 再生コンテナからの現在時刻報告（周期オブザーバ）。スクラブ中は無視する。
    public func updateObservedTime(_ time: Double) {
        guard !isScrubbing, time.isFinite else { return }
        currentTime = min(max(time, 0), duration > 0 ? duration : time)
    }

    /// 再生コンテナから尺のより正確な値が判明したとき更新する（成果物値の補正）。
    public func updateDuration(_ value: Double) {
        guard value.isFinite, value > 0 else { return }
        duration = value
    }

    /// 再生コンテナが終端に達したときの通知。停止し、位置は終端のまま留める。
    /// 次に再生を押したら `togglePlayPause` が先頭へ巻き戻してから再生する。
    public func playbackDidReachEnd() {
        isPlaying = false
    }

    // MARK: - 音量・字幕

    /// 日本語ゲイン設定（0〜1 にクランプ）。再処理ではなく再生層のゲインのみ変える（08 §オーディオ）。
    public func setJapaneseVolume(_ value: Double) {
        japaneseVolume = min(max(value, 0), 1)
    }

    /// 元音声ゲイン設定（0〜1 にクランプ）。
    public func setOriginalVolume(_ value: Double) {
        originalVolume = min(max(value, 0), 1)
    }

    public func toggleSubtitles() {
        subtitlesEnabled.toggle()
    }

    // MARK: - エラー整形

    static let connectionError = BackendErrorBody(
        code: "NOT_CONNECTED",
        stage: nil,
        message: "バックエンドに接続していません。再接続してからお試しください。",
        retryable: true
    )

    private static func errorBody(from error: Error) -> BackendErrorBody {
        if case let BackendError.api(body, _) = error { return body }
        return BackendErrorBody(
            code: "RESULT_UNAVAILABLE",
            stage: nil,
            message: error.localizedDescription,
            retryable: true
        )
    }
}
