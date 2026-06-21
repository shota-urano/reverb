import Testing
import Foundation
@testable import ReverbKit

/// ライブラリ画面ロジック（USL-77）の検証。動画検証・ジョブ作成・失敗時の入力保持を対象にする。
@Suite @MainActor struct LibraryViewModelTests {

    @Test func submitSucceedsAndClearsState() async {
        let vm = LibraryViewModel(jobRepository: StubJobRepository())
        let response = await vm.submit(videoURL: URL(fileURLWithPath: "/Movies/lecture.mp4"))

        #expect(response?.jobId == "j_stub")
        #expect(vm.errorMessage == nil)
        #expect(vm.lastAttemptedPath == nil) // 成功時は入力を解放
        #expect(vm.isCreating == false)
    }

    @Test func submitPassesVideoPathToRepository() async {
        let repo = StubJobRepository()
        let vm = LibraryViewModel(jobRepository: repo)
        _ = await vm.submit(videoURL: URL(fileURLWithPath: "/Movies/lecture.mp4"))
        #expect(repo.recorder.paths == ["/Movies/lecture.mp4"])
    }

    @Test func submitPassesSavedSettingsToRepository() async {
        // 設定画面（USL-80）で保存した既定設定を POST /jobs に渡す。
        let saved = JobSettings(
            stt: STTSettings(model: "turbo", language: nil),
            translate: TranslateSettings(model: "gemma3:27b"),
            tts: TTSSettings(speakerId: 11, styleId: 0),
            mix: MixSettings(jaVolume: 0.9, originalVolume: 0.1)
        )
        let repo = StubJobRepository()
        let vm = LibraryViewModel(jobRepository: repo, settingsStore: InMemorySettingsStore(initial: saved))
        _ = await vm.submit(videoURL: URL(fileURLWithPath: "/Movies/lecture.mp4"))
        #expect(repo.settingsRecorder.last == saved)
    }

    @Test func submitPassesNilSettingsWhenNoneSaved() async {
        // 未保存ならバックエンド既定に委ねる（settings: nil）。
        let repo = StubJobRepository()
        let vm = LibraryViewModel(jobRepository: repo, settingsStore: InMemorySettingsStore())
        _ = await vm.submit(videoURL: URL(fileURLWithPath: "/Movies/lecture.mp4"))
        #expect(repo.settingsRecorder.last == nil)
    }

    @Test func submitRejectsNonMP4WithoutCallingRepository() async {
        let repo = StubJobRepository()
        let vm = LibraryViewModel(jobRepository: repo)
        let response = await vm.submit(videoURL: URL(fileURLWithPath: "/Movies/clip.mov"))

        #expect(response == nil)
        #expect(vm.errorMessage != nil)
        #expect(repo.recorder.paths.isEmpty) // 非対応形式は API を叩かない
    }

    @Test func submitFailureSetsErrorAndRetainsInput() async {
        var repo = StubJobRepository()
        repo.createError = .api(
            BackendErrorBody(code: "OLLAMA_UNAVAILABLE", stage: "translate", message: "Ollama に接続できません", retryable: true),
            statusCode: 503
        )
        let vm = LibraryViewModel(jobRepository: repo)
        let response = await vm.submit(videoURL: URL(fileURLWithPath: "/Movies/lecture.mp4"))

        #expect(response == nil)
        #expect(vm.errorMessage?.contains("Ollama に接続できません") == true)
        #expect(vm.lastAttemptedPath == "/Movies/lecture.mp4") // 失敗時は入力を保持（screens.md §1）
        #expect(vm.isCreating == false)
    }

    @Test func submitWithoutRepositoryFails() async {
        let vm = LibraryViewModel(jobRepository: nil)
        let response = await vm.submit(videoURL: URL(fileURLWithPath: "/Movies/lecture.mp4"))
        #expect(response == nil)
        #expect(vm.errorMessage != nil)
    }

    @Test func dismissErrorClearsMessage() async {
        let vm = LibraryViewModel(jobRepository: nil)
        _ = await vm.submit(videoURL: URL(fileURLWithPath: "/Movies/lecture.mp4"))
        #expect(vm.errorMessage != nil)
        vm.dismissError()
        #expect(vm.errorMessage == nil)
    }

    @Test func submitIgnoresReentryWhileCreating() async {
        // 作成中（最初の createJob を保留）に再投入しても無視され、二重に POST しない。
        let repo = BlockingJobRepository()
        let vm = LibraryViewModel(jobRepository: repo)

        async let first = vm.submit(videoURL: URL(fileURLWithPath: "/Movies/a.mp4"))
        await repo.waitUntilStarted() // 1本目が createJob で保留＝isCreating == true

        let second = await vm.submit(videoURL: URL(fileURLWithPath: "/Movies/b.mp4"))
        #expect(second == nil) // 再入は弾く

        await repo.release()
        let firstResult = await first
        #expect(firstResult?.jobId == "j_block")
        let calls = await repo.callCount
        #expect(calls == 1) // POST は1回だけ
    }

    // MARK: - 純粋ヘルパ

    @Test func isSupportedAcceptsMP4CaseInsensitive() {
        #expect(LibraryViewModel.isSupported(URL(fileURLWithPath: "/a/lecture.mp4")))
        #expect(LibraryViewModel.isSupported(URL(fileURLWithPath: "/a/lecture.MP4")))
        #expect(!LibraryViewModel.isSupported(URL(fileURLWithPath: "/a/lecture.mov")))
        #expect(!LibraryViewModel.isSupported(URL(fileURLWithPath: "/a/lecture")))
    }

    @Test func projectTitleStripsExtension() {
        #expect(LibraryViewModel.projectTitle(from: URL(fileURLWithPath: "/a/b/lecture.mp4")) == "lecture")
        #expect(LibraryViewModel.projectTitle(from: URL(fileURLWithPath: "/a/My Talk.mp4")) == "My Talk")
    }
}
