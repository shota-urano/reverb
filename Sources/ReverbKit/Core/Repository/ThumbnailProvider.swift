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
/// - キャッシュは `NSCache`（件数上限つき）で、大量プロジェクトでも青天井に NSImage を抱えない。
/// - 同一 jobId への同時要求は in-flight タスクを共有して二重取得を防ぐ。
/// - 失敗はキャッシュせず nil を返す（次回再試行を許す）。存在判定は呼び出し側の `hasThumbnail` で行う。
@MainActor
public final class ThumbnailProvider: ThumbnailLoading {
    private let repository: any JobRepository
    private let cache = NSCache<NSString, NSImage>()
    private var inflight: [String: Task<NSImage?, Never>] = [:]

    /// - Parameter cacheCountLimit: 保持するサムネイル枚数の上限（既定 256）。超過分は NSCache が随時破棄する。
    public init(repository: any JobRepository, cacheCountLimit: Int = 256) {
        self.repository = repository
        cache.countLimit = cacheCountLimit
    }

    public func cachedImage(forJob jobId: String) -> NSImage? {
        cache.object(forKey: jobId as NSString)
    }

    public func image(forJob jobId: String) async -> NSImage? {
        if let cached = cache.object(forKey: jobId as NSString) { return cached }
        if let task = inflight[jobId] { return await task.value }

        let repository = self.repository
        let task = Task { () -> NSImage? in
            guard let data = try? await repository.thumbnail(jobId: jobId) else { return nil }
            return NSImage(data: data)
        }
        inflight[jobId] = task
        let image = await task.value
        inflight.removeValue(forKey: jobId)
        if let image { cache.setObject(image, forKey: jobId as NSString) }
        return image
    }
}
