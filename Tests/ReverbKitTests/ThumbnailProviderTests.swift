import AppKit
import Foundation
import Testing
@testable import ReverbKit

/// サムネイル取得のメモリキャッシュ・取得失敗フォールバックの検証（USL-103）。
@MainActor
struct ThumbnailProviderTests {
    @Test func cachesAndAvoidsRefetch() async {
        let repo = CountingThumbnailRepository(data: Self.pngData())
        let provider = ThumbnailProvider(repository: repo)

        let first = await provider.image(forJob: "j1")
        let second = await provider.image(forJob: "j1")

        #expect(first != nil)
        #expect(second != nil)
        #expect(repo.callCount == 1) // 2回目はキャッシュヒットで再取得しない
        #expect(provider.cachedImage(forJob: "j1") != nil)
    }

    @Test func failureFallsBackToNilAndIsNotCached() async {
        let repo = CountingThumbnailRepository(data: nil) // throw → 取得失敗
        let provider = ThumbnailProvider(repository: repo)

        let image = await provider.image(forJob: "j_missing")

        #expect(image == nil) // 呼び出し側はプレースホルダにフォールバック
        #expect(provider.cachedImage(forJob: "j_missing") == nil) // 失敗はキャッシュしない
    }

    @Test func invalidDataFallsBackToNil() async {
        let repo = CountingThumbnailRepository(data: Data([0x00, 0x01, 0x02])) // 画像化できない
        let provider = ThumbnailProvider(repository: repo)

        let image = await provider.image(forJob: "j_bad")

        #expect(image == nil)
    }

    /// 1x1 の PNG バイト列（NSImage 化できる最小の実画像）。
    static func pngData() -> Data {
        let image = NSImage(size: NSSize(width: 1, height: 1))
        image.lockFocus()
        NSColor.black.setFill()
        NSRect(x: 0, y: 0, width: 1, height: 1).fill()
        image.unlockFocus()
        guard let tiff = image.tiffRepresentation,
              let rep = NSBitmapImageRep(data: tiff),
              let png = rep.representation(using: .png, properties: [:]) else {
            return Data()
        }
        return png
    }
}

/// thumbnail 取得回数を数えるテスト用 JobRepository。data が nil なら取得失敗を模す。
private final class CountingThumbnailRepository: JobRepository, @unchecked Sendable {
    private let data: Data?
    private let lock = NSLock()
    private var _callCount = 0
    var callCount: Int { lock.withLock { _callCount } }

    init(data: Data?) { self.data = data }

    func thumbnail(jobId: String) async throws -> Data {
        lock.withLock { _callCount += 1 }
        guard let data else { throw BackendError.http(statusCode: 404) }
        return data
    }

    func createJob(videoPath: String, settings: JobSettings?) async throws -> CreateJobResponse {
        CreateJobResponse(jobId: "j", projectId: "p", status: .queued)
    }
    func listJobs() async throws -> JobListResponse { JobListResponse(items: []) }
    func job(id: String) async throws -> JobStatus { throw BackendError.invalidResponse }
    func cancel(id: String) async throws {}
    func result(id: String) async throws -> JobResult { throw BackendError.invalidResponse }
    func events(id: String) -> AsyncThrowingStream<JobEvent, Error> {
        AsyncThrowingStream { $0.finish() }
    }
}
