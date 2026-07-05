import Foundation
@testable import ReverbKit

/// 削除を使わない既存スタブ向けの no-op 既定（USL-102）。
/// 削除の成否を検証するテストは AppModel 経由で MockBackendClient.deleteError を使う。
extension JobRepository {
    func deleteJob(id: String) async throws {}
    /// サムネイルを使わない既存スタブ向けの既定（USL-103）。空データ＝画像なし扱い。
    func thumbnail(jobId: String) async throws -> Data { Data() }
    /// 再開を使わない既存スタブ向けの既定（USL-116）。jobId 据え置きで queued を返す。
    /// 再開の成否を検証するテストは ScriptedJobRepository の resumeError で制御する。
    func resume(id: String) async throws -> CreateJobResponse {
        CreateJobResponse(jobId: id, projectId: "p_test", status: .queued)
    }
}

/// テスト用の BackendClient。固定値を返す。
struct MockBackendClient: BackendClient {
    var health: HealthResponse = .init(
        status: "ok",
        version: "0.6.0",
        dependencies: .init(ffmpeg: true, mlxWhisper: true, ollama: true, tts: true)
    )
    var models: ModelsResponse = .init(defaultModel: "qwen3:30b", models: ["qwen3:30b"])
    var speakers: SpeakersResponse = .init(
        defaultSpeaker: .init(speakerId: 13, name: "青山龍星", styleId: 0),
        speakers: [.init(speakerId: 13, name: "青山龍星", styleId: 0)]
    )
    /// `GET /jobs` の戻り（既定は空。起動時ライブラリ復元の検証で差し替える / USL-95）。
    var jobList: JobListResponse = .init(items: [])
    /// 非 nil なら `jobs()` がこのエラーで失敗する。
    var jobsError: BackendError?
    /// 非 nil なら `deleteJob(id:)` がこのエラーで失敗する（USL-102 の削除失敗検証用）。
    var deleteError: BackendError?

    func health() async throws -> HealthResponse { health }
    func models() async throws -> ModelsResponse { models }
    func speakers() async throws -> SpeakersResponse { speakers }
    func createJob(_ request: CreateJobRequest) async throws -> CreateJobResponse {
        .init(jobId: "j_test", projectId: "p_test", status: .queued)
    }
    func jobs() async throws -> JobListResponse {
        if let jobsError { throw jobsError }
        return jobList
    }
    func job(id: String) async throws -> JobStatus {
        .init(jobId: id, projectId: "p_test", status: .running, currentStage: .translate,
              progress: 0.4, stages: [], error: nil)
    }
    func cancelJob(id: String) async throws {}
    func resumeJob(id: String) async throws -> CreateJobResponse {
        .init(jobId: id, projectId: "p_test", status: .queued)
    }
    func deleteJob(id: String) async throws {
        if let deleteError { throw deleteError }
    }
    func jobResult(id: String) async throws -> JobResult {
        .init(projectId: "p_test", videoPath: "/v.mp4", voiceoverPath: "/vo.wav",
              subtitlesPath: "/s.json", duration: 1.0)
    }
    /// サムネイル取得（既定は空データ＝画像なし扱い）。
    var thumbnailData: Data = Data()
    func thumbnail(jobId: String) async throws -> Data { thumbnailData }
    func events(jobId: String) -> AsyncThrowingStream<JobEvent, Error> {
        AsyncThrowingStream { $0.finish() }
    }
    func shutdown() async {}
}

/// 設定可能なテスト用 ModelRepository。health/models/speakers を個別に成功値・失敗で制御する。
/// 設定画面（USL-80）の読込・依存ゲート・既定反映の検証に使う。
struct StubModelRepository: ModelRepository {
    var healthResponse = HealthResponse(
        status: "ok",
        version: "0.6.0",
        dependencies: DependencyStatus(ffmpeg: true, mlxWhisper: true, ollama: true, tts: true)
    )
    var modelsResponse = ModelsResponse(defaultModel: "qwen3:30b", models: ["qwen3:30b", "gemma3:27b"])
    var speakersResponse = SpeakersResponse(
        defaultSpeaker: Speaker(speakerId: 13, name: "青山龍星", styleId: 0),
        speakers: [
            Speaker(speakerId: 13, name: "青山龍星", styleId: 0),
            Speaker(speakerId: 11, name: "玄野武宏", styleId: 0),
        ]
    )
    /// 非 nil なら該当呼び出しが失敗する。
    var healthError: BackendError?
    var modelsError: BackendError?
    var speakersError: BackendError?

    func health() async throws -> HealthResponse {
        if let healthError { throw healthError }
        return healthResponse
    }
    func translationModels() async throws -> ModelsResponse {
        if let modelsError { throw modelsError }
        return modelsResponse
    }
    func speakers() async throws -> SpeakersResponse {
        if let speakersError { throw speakersError }
        return speakersResponse
    }
}

/// 設定可能なテスト用 JobRepository。createJob の成否と渡された videoPath / settings を制御・記録する。
struct StubJobRepository: JobRepository {
    var createResponse = CreateJobResponse(jobId: "j_stub", projectId: "p_stub", status: .queued)
    /// 非 nil なら createJob はこのエラーで失敗する。
    var createError: BackendError?
    /// createJob に渡された videoPath の記録。
    var recorder = CallRecorder()
    /// createJob に渡された settings の記録（USL-80 の既定設定受け渡し検証用）。
    var settingsRecorder = SettingsRecorder()

    func createJob(videoPath: String, settings: JobSettings?) async throws -> CreateJobResponse {
        recorder.record(videoPath)
        settingsRecorder.record(settings)
        if let createError { throw createError }
        return createResponse
    }
    func listJobs() async throws -> JobListResponse { JobListResponse(items: []) }
    func job(id: String) async throws -> JobStatus { throw BackendError.invalidResponse }
    func cancel(id: String) async throws {}
    func result(id: String) async throws -> JobResult { throw BackendError.invalidResponse }
    func events(id: String) -> AsyncThrowingStream<JobEvent, Error> {
        AsyncThrowingStream { $0.finish() }
    }
}

/// createJob を任意のタイミングまで中断させられる JobRepository。再入ガードの検証に使う。
/// `waitUntilStarted()` で「createJob に入った」ことを待ち、`release()` まで応答を保留する。
actor BlockingJobRepository: JobRepository {
    private(set) var callCount = 0
    private var gate: CheckedContinuation<Void, Never>?
    private var startedSignal: CheckedContinuation<Void, Never>?

    /// createJob が実際に呼ばれるまで待つ。
    func waitUntilStarted() async {
        await withCheckedContinuation { startedSignal = $0 }
    }

    /// 中断中の createJob を再開させる。
    func release() {
        gate?.resume()
        gate = nil
    }

    func createJob(videoPath: String, settings: JobSettings?) async throws -> CreateJobResponse {
        callCount += 1
        startedSignal?.resume()
        startedSignal = nil
        await withCheckedContinuation { gate = $0 } // release() まで保留（actor 隔離下で gate を確定）
        return CreateJobResponse(jobId: "j_block", projectId: "p_block", status: .queued)
    }

    func listJobs() async throws -> JobListResponse { JobListResponse(items: []) }
    func job(id: String) async throws -> JobStatus { throw BackendError.invalidResponse }
    func cancel(id: String) async throws {}
    func result(id: String) async throws -> JobResult { throw BackendError.invalidResponse }
    nonisolated func events(id: String) -> AsyncThrowingStream<JobEvent, Error> {
        AsyncThrowingStream { $0.finish() }
    }
}

/// 処理中画面（USL-78）の観測検証用 JobRepository。
///
/// `job(id:)` は与えたスナップショット列を先頭から1つずつ返し（最後の1件は据え置き）、
/// `events(id:)` は与えたイベント列を流して終端する。cancel/job の呼び出し回数を記録する。
final class ScriptedJobRepository: JobRepository, @unchecked Sendable {
    private let lock = NSLock()
    private var snapshots: [JobStatus]
    private let scriptedEvents: [JobEvent]
    private let resumeError: BackendError?
    private var _cancelCount = 0
    private var _jobCallCount = 0
    private var _resumeCount = 0

    var cancelCount: Int { lock.withLock { _cancelCount } }
    var jobCallCount: Int { lock.withLock { _jobCallCount } }
    var resumeCount: Int { lock.withLock { _resumeCount } }

    init(snapshots: [JobStatus], events: [JobEvent] = [], resumeError: BackendError? = nil) {
        self.snapshots = snapshots
        self.scriptedEvents = events
        self.resumeError = resumeError
    }

    func createJob(videoPath: String, settings: JobSettings?) async throws -> CreateJobResponse {
        CreateJobResponse(jobId: "j_scripted", projectId: "p_scripted", status: .queued)
    }

    func listJobs() async throws -> JobListResponse { JobListResponse(items: []) }

    func job(id: String) async throws -> JobStatus {
        try lock.withLock {
            _jobCallCount += 1
            if snapshots.count > 1 { return snapshots.removeFirst() }
            guard let last = snapshots.first else { throw BackendError.invalidResponse }
            return last
        }
    }

    func cancel(id: String) async throws { lock.withLock { _cancelCount += 1 } }

    func resume(id: String) async throws -> CreateJobResponse {
        try lock.withLock {
            _resumeCount += 1
            if let resumeError { throw resumeError }
            return CreateJobResponse(jobId: id, projectId: "p_scripted", status: .queued)
        }
    }

    func result(id: String) async throws -> JobResult { throw BackendError.invalidResponse }

    func events(id: String) -> AsyncThrowingStream<JobEvent, Error> {
        let events = scriptedEvents
        return AsyncThrowingStream { continuation in
            for event in events { continuation.yield(event) }
            continuation.finish()
        }
    }
}

/// プレーヤー（USL-79）の成果物取得検証用 JobRepository。
/// `result(id:)` は設定した JobResult を返すか、設定したエラーで失敗する。
struct PlayerStubJobRepository: JobRepository {
    var jobResult = JobResult(
        projectId: "p_play", videoPath: "/v.mp4", voiceoverPath: "/vo.wav",
        subtitlesPath: "/s.json", duration: 120.0
    )
    /// 非 nil なら result(id:) はこのエラーで失敗する。
    var resultError: BackendError?

    func createJob(videoPath: String, settings: JobSettings?) async throws -> CreateJobResponse {
        CreateJobResponse(jobId: "j_play", projectId: "p_play", status: .done)
    }
    func listJobs() async throws -> JobListResponse { JobListResponse(items: []) }
    func job(id: String) async throws -> JobStatus { throw BackendError.invalidResponse }
    func cancel(id: String) async throws {}
    func result(id: String) async throws -> JobResult {
        if let resultError { throw resultError }
        return jobResult
    }
    func events(id: String) -> AsyncThrowingStream<JobEvent, Error> {
        AsyncThrowingStream { $0.finish() }
    }
}

/// テスト用 SubtitleRepository。設定した SubtitleTrack を返すか、エラーで失敗する。
struct StubSubtitleRepository: SubtitleRepository {
    var track = SubtitleTrack(version: 1, cues: [])
    var loadError: Error?

    func load(path: String) async throws -> SubtitleTrack {
        if let loadError { throw loadError }
        return track
    }
}

/// createJob に渡された videoPath を安全に記録する小箱。
final class CallRecorder: @unchecked Sendable {
    private let lock = NSLock()
    private var storage: [String] = []
    var paths: [String] { lock.withLock { storage } }
    func record(_ path: String) { lock.withLock { storage.append(path) } }
}

/// createJob に渡された settings を安全に記録する小箱。
final class SettingsRecorder: @unchecked Sendable {
    private let lock = NSLock()
    private var storage: [JobSettings?] = []
    var values: [JobSettings?] { lock.withLock { storage } }
    var last: JobSettings? { lock.withLock { storage.last ?? nil } }
    func record(_ settings: JobSettings?) { lock.withLock { storage.append(settings) } }
}

/// テスト用のインメモリ SettingsStore。永続化せず保持値を返す。
final class InMemorySettingsStore: SettingsStore, @unchecked Sendable {
    private let lock = NSLock()
    private var stored: JobSettings?

    init(initial: JobSettings? = nil) {
        self.stored = initial
    }

    func load() -> JobSettings? { lock.withLock { stored } }
    func save(_ settings: JobSettings) { lock.withLock { stored = settings } }
    func clear() { lock.withLock { stored = nil } }
}

/// テスト用のサイドカー起動。プロセスを起動せず固定ハンドシェイクを返す。
struct MockSidecarLauncher: SidecarLauncher {
    var handshake = ReadyHandshake(
        event: "ready",
        baseURL: URL(string: "http://127.0.0.1:53412")!,
        pid: 12345,
        version: "0.6.0"
    )
    var error: SidecarError?

    func launch(onTerminate: @escaping @Sendable (Int32) -> Void) async throws -> ReadyHandshake {
        if let error { throw error }
        return handshake
    }
    func terminate() async {}
}

/// onTerminate コールバックを保持し、テストから予期せぬ終了を発火できる launcher。
/// 世代トークンの検証に用いる。
final class ControllableSidecarLauncher: SidecarLauncher, @unchecked Sendable {
    private let lock = NSLock()
    private var handlers: [@Sendable (Int32) -> Void] = []
    let handshake = ReadyHandshake(
        event: "ready",
        baseURL: URL(string: "http://127.0.0.1:53412")!,
        pid: 12345,
        version: "0.6.0"
    )

    func launch(onTerminate: @escaping @Sendable (Int32) -> Void) async throws -> ReadyHandshake {
        lock.withLock { handlers.append(onTerminate) }
        return handshake
    }

    func terminate() async {}

    /// 直近の launch で渡されたハンドラを発火する（古い世代の終了通知を再現）。
    func fireLastTermination(status: Int32 = 1) {
        let handler = lock.withLock { handlers.last }
        handler?(status)
    }
}
