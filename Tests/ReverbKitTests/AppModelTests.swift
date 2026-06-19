import Testing
import Foundation
@testable import ReverbKit

/// AppModel の接続ライフサイクルとナビゲーションを検証する。
@Suite @MainActor struct AppModelTests {

    @Test func startSucceedsAndBuildsRepositories() async {
        let model = AppModel(
            launcher: MockSidecarLauncher(),
            clientFactory: { _ in MockBackendClient() }
        )
        #expect(model.connection == .idle)

        await model.start()

        #expect(model.connection == .ready)
        #expect(model.jobRepository != nil)
        #expect(model.modelRepository != nil)
        #expect(model.health?.version == "0.6.0")
    }

    @Test func startFailsWhenLauncherErrors() async {
        var launcher = MockSidecarLauncher()
        launcher.error = .notConfigured
        let model = AppModel(launcher: launcher, clientFactory: { _ in MockBackendClient() })

        await model.start()

        guard case .failed = model.connection else {
            Issue.record("接続失敗状態になるべき: \(model.connection)")
            return
        }
        #expect(model.jobRepository == nil)
    }

    @Test func startUsesHandshakeBaseURL() async {
        // baseURL をハードコードせずハンドシェイクから受け取って client を構築する（§3.1）。
        let expected = URL(string: "http://127.0.0.1:53412")!
        let box = URLBox()
        let model = AppModel(
            launcher: MockSidecarLauncher(),
            clientFactory: { url in
                box.value = url
                return MockBackendClient()
            }
        )
        await model.start()
        #expect(box.value == expected)
    }

    @Test func defaultSelectionIsLibrary() {
        let model = AppModel(launcher: MockSidecarLauncher())
        #expect(model.selection == .library)
    }

    @Test func openDoneProjectNavigates() {
        let model = AppModel(launcher: MockSidecarLauncher())
        let done = RecentProject(id: "p1", title: "完了", updatedAt: .init(timeIntervalSince1970: 0), state: .done)
        model.open(done)
        #expect(model.selection == .library) // 完了 → プレーヤー（Library 配下）
    }

    @Test func retryReconnectsToReady() async {
        let model = AppModel(
            launcher: MockSidecarLauncher(),
            clientFactory: { _ in MockBackendClient() }
        )
        await model.start()
        #expect(model.connection == .ready)
        await model.retry()
        #expect(model.connection == .ready)
    }

    @Test func unexpectedTerminationFailsCurrentConnection() async {
        let launcher = ControllableSidecarLauncher()
        let model = AppModel(launcher: launcher, clientFactory: { _ in MockBackendClient() })
        await model.start()
        #expect(model.connection == .ready)

        launcher.fireLastTermination(status: 9)
        // Task { @MainActor } 経由で反映されるため 1 サイクル待つ。
        await Task.yield()
        await Task.yield()
        guard case .failed = model.connection else {
            Issue.record("予期せぬ終了で failed になるべき: \(model.connection)")
            return
        }
        #expect(model.jobRepository == nil)
    }

    @Test func openRunningProjectNavigatesToProcessing() {
        let model = AppModel(launcher: MockSidecarLauncher())
        let running = RecentProject(
            id: "p2", title: "処理中", updatedAt: .init(timeIntervalSince1970: 0),
            state: .running, jobId: "j2"
        )
        model.open(running)
        #expect(model.selection == .processing)
    }
}

/// clientFactory（@Sendable）に渡る URL を安全に受け取るための小箱。
private final class URLBox: @unchecked Sendable {
    private let lock = NSLock()
    private var storage: URL?
    var value: URL? {
        get { lock.withLock { storage } }
        set { lock.withLock { storage = newValue } }
    }
}
