import Foundation
@testable import ReverbKit

/// テスト用の BackendClient。固定値を返す。
struct MockBackendClient: BackendClient {
    var health: HealthResponse = .init(
        status: "ok",
        version: "0.6.0",
        dependencies: .init(ffmpeg: true, mlxWhisper: true, ollama: true, voicevox: true)
    )
    var models: ModelsResponse = .init(defaultModel: "qwen3:30b", models: ["qwen3:30b"])
    var speakers: SpeakersResponse = .init(
        defaultSpeaker: .init(speakerId: 13, name: "青山龍星", styleId: 0),
        speakers: [.init(speakerId: 13, name: "青山龍星", styleId: 0)]
    )

    func health() async throws -> HealthResponse { health }
    func models() async throws -> ModelsResponse { models }
    func speakers() async throws -> SpeakersResponse { speakers }
    func createJob(_ request: CreateJobRequest) async throws -> CreateJobResponse {
        .init(jobId: "j_test", projectId: "p_test", status: .queued)
    }
    func job(id: String) async throws -> JobStatus {
        .init(jobId: id, projectId: "p_test", status: .running, currentStage: .translate,
              progress: 0.4, stages: [], error: nil)
    }
    func cancelJob(id: String) async throws {}
    func jobResult(id: String) async throws -> JobResult {
        .init(projectId: "p_test", videoPath: "/v.mp4", voiceoverPath: "/vo.wav",
              subtitlesPath: "/s.json", duration: 1.0)
    }
    func events(jobId: String) -> AsyncThrowingStream<JobEvent, Error> {
        AsyncThrowingStream { $0.finish() }
    }
    func shutdown() async {}
}

/// 設定可能なテスト用 JobRepository。createJob の成否と渡された videoPath を制御・記録する。
struct StubJobRepository: JobRepository {
    var createResponse = CreateJobResponse(jobId: "j_stub", projectId: "p_stub", status: .queued)
    /// 非 nil なら createJob はこのエラーで失敗する。
    var createError: BackendError?
    /// createJob に渡された videoPath の記録。
    var recorder = CallRecorder()

    func createJob(videoPath: String, settings: JobSettings?) async throws -> CreateJobResponse {
        recorder.record(videoPath)
        if let createError { throw createError }
        return createResponse
    }
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
    private var _cancelCount = 0
    private var _jobCallCount = 0

    var cancelCount: Int { lock.withLock { _cancelCount } }
    var jobCallCount: Int { lock.withLock { _jobCallCount } }

    init(snapshots: [JobStatus], events: [JobEvent] = []) {
        self.snapshots = snapshots
        self.scriptedEvents = events
    }

    func createJob(videoPath: String, settings: JobSettings?) async throws -> CreateJobResponse {
        CreateJobResponse(jobId: "j_scripted", projectId: "p_scripted", status: .queued)
    }

    func job(id: String) async throws -> JobStatus {
        try lock.withLock {
            _jobCallCount += 1
            if snapshots.count > 1 { return snapshots.removeFirst() }
            guard let last = snapshots.first else { throw BackendError.invalidResponse }
            return last
        }
    }

    func cancel(id: String) async throws { lock.withLock { _cancelCount += 1 } }
    func result(id: String) async throws -> JobResult { throw BackendError.invalidResponse }

    func events(id: String) -> AsyncThrowingStream<JobEvent, Error> {
        let events = scriptedEvents
        return AsyncThrowingStream { continuation in
            for event in events { continuation.yield(event) }
            continuation.finish()
        }
    }
}

/// createJob に渡された videoPath を安全に記録する小箱。
final class CallRecorder: @unchecked Sendable {
    private let lock = NSLock()
    private var storage: [String] = []
    var paths: [String] { lock.withLock { storage } }
    func record(_ path: String) { lock.withLock { storage.append(path) } }
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
