import Foundation

/// ジョブ（パイプライン実行）の取得・操作境界。ViewModel はこの protocol 経由で状態を取得する
/// （View に処理ロジックを置かない / ルール3）。
public protocol JobRepository: Sendable {
    func createJob(videoPath: String, settings: JobSettings?) async throws -> CreateJobResponse
    func job(id: String) async throws -> JobStatus
    func cancel(id: String) async throws
    func result(id: String) async throws -> JobResult
    /// 進捗ストリーム（SSE）。ポーリングのフォールバックは ViewModel 側で選択する。
    func events(id: String) -> AsyncThrowingStream<JobEvent, Error>
}

/// `BackendClient` を包む既定実装。
public struct DefaultJobRepository: JobRepository {
    private let client: any BackendClient

    public init(client: any BackendClient) {
        self.client = client
    }

    public func createJob(videoPath: String, settings: JobSettings?) async throws -> CreateJobResponse {
        try await client.createJob(CreateJobRequest(videoPath: videoPath, settings: settings))
    }

    public func job(id: String) async throws -> JobStatus {
        try await client.job(id: id)
    }

    public func cancel(id: String) async throws {
        try await client.cancelJob(id: id)
    }

    public func result(id: String) async throws -> JobResult {
        try await client.jobResult(id: id)
    }

    public func events(id: String) -> AsyncThrowingStream<JobEvent, Error> {
        client.events(jobId: id)
    }
}
