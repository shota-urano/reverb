import Foundation

/// ジョブ（パイプライン実行）の取得・操作境界。ViewModel はこの protocol 経由で状態を取得する
/// （View に処理ロジックを置かない / ルール3）。
public protocol JobRepository: Sendable {
    func createJob(videoPath: String, settings: JobSettings?) async throws -> CreateJobResponse
    /// 永続プロジェクト一覧（`GET /jobs` / USL-94）。起動時のライブラリ復元に使う。新しい順。
    func listJobs() async throws -> JobListResponse
    func job(id: String) async throws -> JobStatus
    func cancel(id: String) async throws
    /// プロジェクト削除（`DELETE /jobs/{id}` / USL-99）。実行中は backend が 409 で拒否するため失敗を投げる。
    func deleteJob(id: String) async throws
    func result(id: String) async throws -> JobResult
    /// サムネイル画像バイナリ（`GET /jobs/{id}/thumbnail` / USL-103）。未生成は backend が 404 を返す。
    /// 一覧の `hasThumbnail` が真のものだけ呼び、無駄な 404 を避ける。
    func thumbnail(jobId: String) async throws -> Data
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

    public func listJobs() async throws -> JobListResponse {
        try await client.jobs()
    }

    public func job(id: String) async throws -> JobStatus {
        try await client.job(id: id)
    }

    public func cancel(id: String) async throws {
        try await client.cancelJob(id: id)
    }

    public func deleteJob(id: String) async throws {
        try await client.deleteJob(id: id)
    }

    public func result(id: String) async throws -> JobResult {
        try await client.jobResult(id: id)
    }

    public func thumbnail(jobId: String) async throws -> Data {
        try await client.thumbnail(jobId: jobId)
    }

    public func events(id: String) -> AsyncThrowingStream<JobEvent, Error> {
        client.events(jobId: id)
    }
}
