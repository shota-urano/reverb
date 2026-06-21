import Testing
import Foundation
@testable import ReverbKit

/// プレーヤー（USL-79）の状態遷移・字幕選択・エラー判定・音量制御を検証する。
/// AVFoundation を持たない VM の純粋部分のみを対象にする（再生配線は PlaybackCoordinator・View）。
@Suite @MainActor struct PlayerViewModelTests {

    private func makeViewModel(
        repo: PlayerStubJobRepository = PlayerStubJobRepository(),
        subtitles: StubSubtitleRepository = StubSubtitleRepository(),
        fileExists: @escaping @Sendable (String) -> Bool = { _ in true }
    ) -> PlayerViewModel {
        PlayerViewModel(
            jobRepository: repo,
            subtitleRepository: subtitles,
            modelRepository: nil,
            fileExists: fileExists
        )
    }

    // MARK: - 読込

    @Test func loadSuccessMakesPlayable() async {
        let cues = [SubtitleCue(id: 0, start: 0, end: 4.2, lines: ["一"])]
        let vm = makeViewModel(subtitles: StubSubtitleRepository(track: .init(version: 1, cues: cues)))
        await vm.load(jobId: "j")

        #expect(vm.phase == .ready)
        #expect(vm.canPlay)
        #expect(vm.duration == 120.0)
        #expect(vm.videoMissing == false)
        #expect(vm.voiceoverMissing == false)
        #expect(vm.subtitleUnavailable == false)
        #expect(vm.subtitleTrack?.cues.count == 1)
    }

    @Test func videoMissingBlocksPlayback() async {
        let vm = makeViewModel(fileExists: { $0 != "/v.mp4" }) // 元動画だけ無い
        await vm.load(jobId: "j")
        #expect(vm.videoMissing)
        #expect(vm.canPlay == false) // 再生を始めない（08 §エラー）
        #expect(vm.phase == .ready)  // 画面自体は出す（再選択を促す）
    }

    @Test func voiceoverMissingBlocksPlayback() async {
        let vm = makeViewModel(fileExists: { $0 != "/vo.wav" }) // 吹き替えだけ無い
        await vm.load(jobId: "j")
        #expect(vm.voiceoverMissing)
        #expect(vm.canPlay == false)
    }

    @Test func subtitleMissingStillPlays() async {
        let vm = makeViewModel(fileExists: { $0 != "/s.json" }) // 字幕だけ無い
        await vm.load(jobId: "j")
        #expect(vm.subtitleUnavailable)
        #expect(vm.canPlay) // 動画・音声は再生できる（08 §エラー）
    }

    @Test func subtitleDecodeFailureStillPlays() async {
        let broken = StubSubtitleRepository(loadError: BackendError.decoding("壊れた JSON"))
        let vm = makeViewModel(subtitles: broken)
        await vm.load(jobId: "j")
        #expect(vm.subtitleUnavailable)
        #expect(vm.subtitleTrack == nil)
        #expect(vm.canPlay)
    }

    @Test func resultFetchFailureSetsFailedPhase() async {
        let body = BackendErrorBody(code: "MIX_FAILED", stage: "mix", message: "失敗", retryable: false)
        let repo = PlayerStubJobRepository(resultError: .api(body, statusCode: 500))
        let vm = makeViewModel(repo: repo)
        await vm.load(jobId: "j")
        #expect(vm.phase == .failed(body))
        #expect(vm.canPlay == false)
    }

    @Test func notConnectedFailsLoad() async {
        let vm = PlayerViewModel(jobRepository: nil, subtitleRepository: StubSubtitleRepository())
        await vm.load(jobId: "j")
        guard case .failed(let body) = vm.phase else {
            Issue.record("未接続は failed になるべき: \(vm.phase)")
            return
        }
        #expect(body.code == "NOT_CONNECTED")
    }

    // MARK: - 字幕表示（ON/OFF・時刻同期）

    @Test func currentLinesFollowTimeAndToggle() async {
        let cues = [SubtitleCue(id: 0, start: 0, end: 4.2, lines: ["一"])]
        let vm = makeViewModel(subtitles: StubSubtitleRepository(track: .init(version: 1, cues: cues)))
        await vm.load(jobId: "j")

        vm.seek(toTime: 1.0)
        #expect(vm.currentLines == ["一"])

        vm.seek(toTime: 5.0) // cue の外
        #expect(vm.currentLines == [])

        vm.seek(toTime: 1.0)
        vm.toggleSubtitles() // OFF は表示のみ切替（08 §字幕）
        #expect(vm.subtitlesEnabled == false)
        #expect(vm.currentLines == [])
    }

    // MARK: - 再生操作

    @Test func togglePlayPauseRequiresPlayable() async {
        let vm = makeViewModel(fileExists: { $0 != "/vo.wav" }) // 再生不能
        await vm.load(jobId: "j")
        vm.togglePlayPause()
        #expect(vm.isPlaying == false) // 成果物欠落では再生を始めない
    }

    @Test func togglePlayPauseFlipsWhenPlayable() async {
        let vm = makeViewModel()
        await vm.load(jobId: "j")
        vm.togglePlayPause()
        #expect(vm.isPlaying)
        vm.togglePlayPause()
        #expect(vm.isPlaying == false)
    }

    @Test func playFromEndRewindsToStart() async {
        let vm = makeViewModel()
        await vm.load(jobId: "j") // duration 120
        vm.seek(toTime: 120)      // 終端
        vm.playbackDidReachEnd()
        #expect(vm.isPlaying == false)
        #expect(vm.currentTime == 120)

        vm.togglePlayPause()      // 終端から再生 → 先頭へ巻き戻して再生
        #expect(vm.currentTime == 0)
        #expect(vm.isPlaying)
    }

    @Test func seekClampsAndBumpsToken() async {
        let vm = makeViewModel()
        await vm.load(jobId: "j") // duration 120
        let token0 = vm.seekToken

        vm.seek(toTime: 200) // 上限クランプ
        #expect(vm.currentTime == 120)
        #expect(vm.seekToken == token0 + 1)

        vm.seek(toTime: -5) // 下限クランプ
        #expect(vm.currentTime == 0)
    }

    @Test func scrubbingIgnoresObservedTime() async {
        let vm = makeViewModel()
        await vm.load(jobId: "j")
        vm.beginScrubbing()
        vm.updateObservedTime(50) // スクラブ中は無視
        #expect(vm.currentTime == 0)
        vm.endScrubbing(atFraction: 0.5) // 0.5 * 120
        #expect(vm.currentTime == 60)
        #expect(vm.isScrubbing == false)
    }

    @Test func progressReflectsPosition() async {
        let vm = makeViewModel()
        await vm.load(jobId: "j")
        vm.seek(toTime: 30)
        #expect(vm.progress == 0.25)
    }

    // MARK: - 音量（確定初期値・クランプ）

    @Test func volumesStartAtConfirmedInitial() {
        let vm = makeViewModel()
        // ルール4: 日本語100% / 元音声8%。
        #expect(vm.japaneseVolume == 1.0)
        #expect(vm.originalVolume == 0.08)
    }

    @Test func volumesClampToUnitRange() {
        let vm = makeViewModel()
        vm.setJapaneseVolume(2.0)
        #expect(vm.japaneseVolume == 1.0)
        vm.setOriginalVolume(-1.0)
        #expect(vm.originalVolume == 0.0)
        vm.setOriginalVolume(0.5)
        #expect(vm.originalVolume == 0.5)
    }
}
