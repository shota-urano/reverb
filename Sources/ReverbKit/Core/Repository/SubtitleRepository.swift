import Foundation

/// 字幕トラック（`subtitles.json`）の読み込み境界。
///
/// 字幕は成果物としてローカルディスクに置かれ、`GET /jobs/{id}/result` が返す
/// `subtitlesPath` を読む（ローカル完結 / ルール1）。HTTP ではなくファイル読込なので
/// BackendClient とは別境界にし、テスト時はモックへ差し替える（ルール3）。
public protocol SubtitleRepository: Sendable {
    func load(path: String) async throws -> SubtitleTrack
}

/// ローカルファイルから `subtitles.json` を読む既定実装。
public struct DefaultSubtitleRepository: SubtitleRepository {
    private let decoder: JSONDecoder

    public init() {
        self.decoder = JSONDecoder()
    }

    public func load(path: String) async throws -> SubtitleTrack {
        // 字幕 JSON は小さいので同期読込で十分。デコード失敗・欠落は呼び出し側（ViewModel）が
        // 「字幕のみ欠落」エラーとして扱い、動画・音声の再生は止めない（08 §エラー）。
        let url = URL(fileURLWithPath: path)
        let data = try Data(contentsOf: url)
        return try decoder.decode(SubtitleTrack.self, from: data)
    }
}
