import Testing
import Foundation
@testable import ReverbKit

/// 処理中画面ロジック（USL-78）の検証。
/// 進捗の反映（スナップショット/SSE）、SSE→ポーリングのフォールバック、終了状態の確定、
/// キャンセル、翻訳モデル取得を対象にする。タイミング依存を避けるため pollInterval は最小化する。
@Suite @MainActor struct ProcessingViewModelTests {

    // MARK: - ファクトリ

    private func status(
        _ state: JobState,
        stage: StageName? = nil,
        progress: Double = 0,
        stages: [StageProgress] = [],
        error: BackendErrorBody? = nil
    ) -> JobStatus {
        JobStatus(
            jobId: "j", projectId: "p", status: state,
            currentStage: stage, progress: progress, stages: stages, error: error
        )
    }

    private func makeVM(
        snapshots: [JobStatus],
        events: [JobEvent] = [],
        model: (any ModelRepository)? = nil
    ) -> (ProcessingViewModel, ScriptedJobRepository) {
        let repo = ScriptedJobRepository(snapshots: snapshots, events: events)
        let vm = ProcessingViewModel(
            jobRepository: repo,
            modelRepository: model,
            pollInterval: .milliseconds(1)
        )
        return (vm, repo)
    }

    // MARK: - リデューサ

    @Test func applySnapshotMapsAllFields() {
        let (vm, _) = makeVM(snapshots: [status(.queued)])
        let snapshot = status(
            .running, stage: .translate, progress: 0.42,
            stages: [StageProgress(name: .extract, status: .done, progress: 1.0)],
            error: nil
        )
        vm.apply(snapshot)
        #expect(vm.status == .running)
        #expect(vm.currentStage == .translate)
        #expect(vm.progress == 0.42)
        #expect(vm.stages.count == 1)
    }

    @Test func applyProgressEventSetsRunning() {
        let (vm, _) = makeVM(snapshots: [status(.queued)])
        vm.apply(.progress(JobProgressEvent(currentStage: .tts, progress: 0.66, stages: [])))
        #expect(vm.status == .running)
        #expect(vm.currentStage == .tts)
        #expect(vm.progress == 0.66)
    }

    @Test func applyDoneEventCompletes() {
        let (vm, _) = makeVM(snapshots: [status(.queued)])
        vm.apply(.done(JobDoneEvent(
            projectId: "p",
            result: JobResult(projectId: "p", videoPath: "/v.mp4", voiceoverPath: "/vo.wav", subtitlesPath: "/s.json", duration: 10)
        )))
        #expect(vm.status == .done)
        #expect(vm.progress == 1)
        #expect(vm.currentStage == nil)
    }

    @Test func terminalStatusIgnoresLateProgressEvent() {
        let (vm, _) = makeVM(snapshots: [status(.queued)])
        vm.apply(status(.canceled)) // 終了状態を確定
        vm.apply(.progress(JobProgressEvent(currentStage: .mix, progress: 0.9, stages: [])))
        #expect(vm.status == .canceled) // 遅延イベントで巻き戻さない
    }

    // MARK: - 派生状態

    @Test func isTerminalCoversAllStates() {
        #expect(!ProcessingViewModel.isTerminal(.queued))
        #expect(!ProcessingViewModel.isTerminal(.running))
        #expect(ProcessingViewModel.isTerminal(.done))
        #expect(ProcessingViewModel.isTerminal(.failed))
        #expect(ProcessingViewModel.isTerminal(.canceled))
    }

    // MARK: - 観測

    @Test func observeSeedsFromSnapshotAndStopsWhenAlreadyDone() async {
        let (vm, repo) = makeVM(snapshots: [status(.done, progress: 1.0)])
        await vm.observe(jobId: "j")
        #expect(vm.status == .done)
        #expect(repo.jobCallCount == 1) // 終了済みは1回のスナップショットで確定（SSE/ポーリング不要）
    }

    @Test func observeAppliesProgressThenDoneViaSSE() async {
        let (vm, _) = makeVM(
            snapshots: [status(.running, stage: .translate, progress: 0.3)],
            events: [
                .progress(JobProgressEvent(currentStage: .tts, progress: 0.7, stages: [])),
                .done(JobDoneEvent(
                    projectId: "p",
                    result: JobResult(projectId: "p", videoPath: "/v.mp4", voiceoverPath: "/vo.wav", subtitlesPath: "/s.json", duration: 10)
                )),
            ]
        )
        await vm.observe(jobId: "j")
        #expect(vm.status == .done)
        #expect(vm.progress == 1)
    }

    @Test func observeFallsBackToPollingWhenSSEEndsWithoutDone() async {
        // SSE は空で終端 → ポーリングで failed を確定する。
        let failure = BackendErrorBody(code: "OLLAMA_UNAVAILABLE", stage: "translate", message: "Ollama に接続できません", retryable: true)
        let (vm, _) = makeVM(
            snapshots: [
                status(.running, stage: .translate, progress: 0.3),
                status(.failed, stage: .translate, progress: 0.3, error: failure),
            ],
            events: [] // SSE 即終端
        )
        await vm.observe(jobId: "j")
        #expect(vm.status == .failed)
        #expect(vm.failure?.code == "OLLAMA_UNAVAILABLE")
    }

    @Test func observeWithoutRepositoryReportsConnectionLost() async {
        let vm = ProcessingViewModel(jobRepository: nil, modelRepository: nil)
        await vm.observe(jobId: "j")
        #expect(vm.connectionLost)
    }

    @Test func observeLoadsTranslateModelFromAPI() async {
        let (vm, _) = makeVM(
            snapshots: [status(.done, progress: 1.0)],
            model: DefaultModelRepository(client: MockBackendClient())
        )
        await vm.observe(jobId: "j")
        #expect(vm.translateModel == "qwen3:30b") // ハードコードでなく /models 由来（ルール6）
    }

    // MARK: - キャンセル

    @Test func cancelRequestsBackendAndMarksCanceled() async {
        let (vm, repo) = makeVM(snapshots: [status(.running, stage: .translate, progress: 0.4)])
        await vm.cancel(jobId: "j")
        #expect(repo.cancelCount == 1)
        #expect(vm.status == .canceled)
    }

    @Test func cancelIsNoOpWhenAlreadyTerminal() async {
        let (vm, repo) = makeVM(snapshots: [status(.done, progress: 1.0)])
        await vm.observe(jobId: "j") // done に確定
        await vm.cancel(jobId: "j")
        #expect(repo.cancelCount == 0) // 終了済みはキャンセルしない
        #expect(!vm.canCancel)
    }
}
