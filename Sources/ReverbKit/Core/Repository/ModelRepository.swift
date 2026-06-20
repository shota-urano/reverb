import Foundation

/// 翻訳モデル・TTS 話者・依存エンジン状態の取得境界。
/// モデル名・話者は API から動的取得し、UI コードに固定しない（ルール5,6）。
public protocol ModelRepository: Sendable {
    func health() async throws -> HealthResponse
    func translationModels() async throws -> ModelsResponse
    func speakers() async throws -> SpeakersResponse
}

/// `BackendClient` を包む既定実装。
public struct DefaultModelRepository: ModelRepository {
    private let client: any BackendClient

    public init(client: any BackendClient) {
        self.client = client
    }

    public func health() async throws -> HealthResponse {
        try await client.health()
    }

    public func translationModels() async throws -> ModelsResponse {
        try await client.models()
    }

    public func speakers() async throws -> SpeakersResponse {
        try await client.speakers()
    }
}
