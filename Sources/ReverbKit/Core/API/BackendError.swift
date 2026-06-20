import Foundation

/// バックエンド連携で発生するエラー。失敗は黙ってスキップせず必ず理由を持つ（ルール / §5）。
public enum BackendError: Error, Sendable, Equatable, LocalizedError {
    /// HTTP 非 2xx だがエラーボディを解釈できた場合（01-architecture §5）。
    case api(BackendErrorBody, statusCode: Int)
    /// HTTP 非 2xx でボディを解釈できなかった場合。
    case http(statusCode: Int)
    /// レスポンスが期待した型でデコードできなかった。
    case decoding(String)
    /// URLSession 等のトランスポート層エラー。
    case transport(String)
    /// レスポンスが HTTPURLResponse でない等の不正応答。
    case invalidResponse

    // LocalizedError.errorDescription を実装する。これにより generic Error / NSError 経由でも
    // カスタムメッセージが保持される（localizedDescription はこの値を返すようになる）。
    public var errorDescription: String? {
        switch self {
        case let .api(body, statusCode):
            return "[\(statusCode)] \(body.code): \(body.message)"
        case let .http(statusCode):
            return "HTTP エラー (\(statusCode))"
        case let .decoding(detail):
            return "レスポンス解釈に失敗: \(detail)"
        case let .transport(detail):
            return "通信に失敗: \(detail)"
        case .invalidResponse:
            return "不正なレスポンスを受信しました"
        }
    }
}
