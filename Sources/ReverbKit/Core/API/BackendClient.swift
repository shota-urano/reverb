import Foundation

/// バックエンド HTTP API（01-architecture §4）への低レベルアクセス境界。
///
/// baseURL はサイドカーのハンドシェイクから受領する（ハードコード禁止）。
/// テスト時はモックに差し替えられるよう protocol で切る。
public protocol BackendClient: Sendable {
    func health() async throws -> HealthResponse
    func models() async throws -> ModelsResponse
    func speakers() async throws -> SpeakersResponse
    func createJob(_ request: CreateJobRequest) async throws -> CreateJobResponse
    func job(id: String) async throws -> JobStatus
    func cancelJob(id: String) async throws
    func jobResult(id: String) async throws -> JobResult
    /// 進捗 SSE（`GET /jobs/{id}/events`）。ポーリングのフォールバックは Repository 側で選択する。
    func events(jobId: String) -> AsyncThrowingStream<JobEvent, Error>
    /// アプリ終了時の安全停止（`POST /shutdown`）。失敗しても投げない。
    func shutdown() async
}

/// URLSession を用いた `BackendClient` 実装。`127.0.0.1` のローカル限定。
public final class HTTPBackendClient: BackendClient {
    private let baseURL: URL
    private let session: URLSession
    private let decoder: JSONDecoder
    private let encoder: JSONEncoder

    public init(baseURL: URL, session: URLSession = .shared) {
        self.baseURL = baseURL
        self.session = session
        self.decoder = JSONDecoder()
        self.encoder = JSONEncoder()
    }

    // MARK: - エンドポイント

    public func health() async throws -> HealthResponse {
        try await get("health")
    }

    public func models() async throws -> ModelsResponse {
        try await get("models")
    }

    public func speakers() async throws -> SpeakersResponse {
        try await get("speakers")
    }

    public func createJob(_ request: CreateJobRequest) async throws -> CreateJobResponse {
        try await post("jobs", body: request)
    }

    public func job(id: String) async throws -> JobStatus {
        try await get("jobs/\(id)")
    }

    public func cancelJob(id: String) async throws {
        let _: EmptyResponse = try await post("jobs/\(id)/cancel", body: EmptyBody())
    }

    public func jobResult(id: String) async throws -> JobResult {
        try await get("jobs/\(id)/result")
    }

    public func shutdown() async {
        // 終了処理。応答可否に関わらず投げない。
        var request = URLRequest(url: url(for: "shutdown"))
        request.httpMethod = "POST"
        _ = try? await session.data(for: request)
    }

    // MARK: - SSE

    public func events(jobId: String) -> AsyncThrowingStream<JobEvent, Error> {
        let url = url(for: "jobs/\(jobId)/events")
        let session = self.session
        let decoder = self.decoder
        return AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    var request = URLRequest(url: url)
                    request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
                    let (bytes, response) = try await session.bytes(for: request)
                    guard let http = response as? HTTPURLResponse else {
                        throw BackendError.invalidResponse
                    }
                    guard (200..<300).contains(http.statusCode) else {
                        throw BackendError.http(statusCode: http.statusCode)
                    }

                    var eventName = "message"
                    var dataLines: [String] = []

                    func dispatch() throws {
                        defer {
                            eventName = "message"
                            dataLines.removeAll(keepingCapacity: true)
                        }
                        guard !dataLines.isEmpty else { return }
                        let payload = Data(dataLines.joined(separator: "\n").utf8)
                        switch eventName {
                        case "progress":
                            let event = try decoder.decode(JobProgressEvent.self, from: payload)
                            continuation.yield(.progress(event))
                        case "done":
                            let event = try decoder.decode(JobDoneEvent.self, from: payload)
                            continuation.yield(.done(event))
                            continuation.finish()
                        default:
                            break // 未知イベントは無視
                        }
                    }

                    for try await rawLine in bytes.lines {
                        // SSE は CRLF / CR / LF いずれの改行も許容。`lines` は LF 区切りのため
                        // CRLF サーバだと末尾に \r が残る。除去しないと data JSON のデコードが失敗する。
                        let line = rawLine.hasSuffix("\r") ? String(rawLine.dropLast()) : rawLine
                        if line.isEmpty {
                            try dispatch() // 空行＝イベント区切り
                        } else if line.hasPrefix(":") {
                            continue // コメント行
                        } else if let value = Self.sseValue(line, field: "event") {
                            eventName = value
                        } else if let value = Self.sseValue(line, field: "data") {
                            dataLines.append(value)
                        }
                    }
                    try dispatch() // ストリーム終端
                    continuation.finish()
                } catch is CancellationError {
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    /// `field: value` 形式の SSE 行から value を取り出す（コロン後の先頭1スペースを除去）。
    private static func sseValue(_ line: String, field: String) -> String? {
        guard line.hasPrefix("\(field):") else { return nil }
        var value = String(line.dropFirst(field.count + 1))
        if value.hasPrefix(" ") { value.removeFirst() }
        return value
    }

    // MARK: - HTTP ヘルパ

    private func url(for path: String) -> URL {
        baseURL.appendingPathComponent(path)
    }

    private func get<T: Decodable>(_ path: String) async throws -> T {
        var request = URLRequest(url: url(for: path))
        request.httpMethod = "GET"
        return try await send(request)
    }

    private func post<Body: Encodable, T: Decodable>(_ path: String, body: Body) async throws -> T {
        var request = URLRequest(url: url(for: path))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if !(body is EmptyBody) {
            request.httpBody = try encoder.encode(body)
        }
        return try await send(request)
    }

    private func send<T: Decodable>(_ request: URLRequest) async throws -> T {
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch is CancellationError {
            throw CancellationError() // キャンセルは握り潰さず伝播させる。
        } catch {
            throw BackendError.transport(error.localizedDescription)
        }
        guard let http = response as? HTTPURLResponse else {
            throw BackendError.invalidResponse
        }
        guard (200..<300).contains(http.statusCode) else {
            // エラーボディを解釈できればコード付きで投げる。
            if let envelope = try? decoder.decode(BackendErrorResponse.self, from: data) {
                throw BackendError.api(envelope.error, statusCode: http.statusCode)
            }
            throw BackendError.http(statusCode: http.statusCode)
        }
        if T.self == EmptyResponse.self {
            return EmptyResponse() as! T
        }
        do {
            return try decoder.decode(T.self, from: data)
        } catch {
            throw BackendError.decoding(error.localizedDescription)
        }
    }
}

/// ボディ無し POST 用の空エンコード型。
private struct EmptyBody: Encodable {}

/// 本文を読まないレスポンス用のプレースホルダ。
private struct EmptyResponse: Decodable {}
