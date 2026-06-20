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
