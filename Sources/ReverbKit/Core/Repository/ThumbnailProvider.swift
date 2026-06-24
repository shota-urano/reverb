import AppKit
import Foundation

/// サムネイル画像の取得・メモリキャッシュ境界（USL-103）。
///
/// ライブラリ行（`ProjectRow`）が行ごと・非同期にサムネイルを取得する際の単一情報源。
/// jobId をキーにメモリキャッシュし、スクロールでの再取得・チラつきを抑える。
/// View → この protocol → `JobRepository` の順でロジックを隔離する（View に処理を置かない / ルール3）。
@MainActor
public protocol ThumbnailLoading: AnyObject {
    /// キャッシュ済み画像を同期取得する（未取得は nil）。チラつき防止の即時表示に使う。
    func cachedImage(forJob jobId: String) -> NSImage?
    /// サムネイルを取得する。キャッシュがあればそれを返し、無ければ取得してキャッシュする。
    /// 取得失敗・未生成は nil（呼び出し側はプレースホルダにフォールバックする）。
    func image(forJob jobId: String) async -> NSImage?
}

/// `JobRepository` 経由でサムネイルを取得し、メモリにキャッシュする既定実装。
///
/// - メモリ内キャッシュ（jobId キー）で再取得を抑制する（ディスク永続化はスコープ外）。
/// - 同一 jobId への同時要求は in-flight タスクを共有して二重取得を防ぐ。
/// - 失敗はキャッシュせず nil を返す（次回再試行を許す）。存在判定は呼び出し側の `hasThumbnail` で行う。
@MainActor
public final class ThumbnailProvider: ThumbnailLoading {
    private let repository: any JobRepository
    private var cache: [String: NSImage] = [:]
    private var inflight: [String: Task<NSImage?, Never>] = [:]

    public init(repository: any JobRepository) {
        self.repository = repository
    }

    public func cachedImage(forJob jobId: String) -> NSImage? {
        cache[jobId]
    }

    public func image(forJob jobId: String) async -> NSImage? {
        if let cached = cache[jobId] { return cached }
        if let task = inflight[jobId] { return await task.value }

        let repository = self.repository
        let task = Task { () -> NSImage? in
            guard let data = try? await repository.thumbnail(jobId: jobId) else { return nil }
            return NSImage(data: data)
        }
        inflight[jobId] = task
        let image = await task.value
        inflight.removeValue(forKey: jobId)
        if let image { cache[jobId] = image }
        return image
    }
}
