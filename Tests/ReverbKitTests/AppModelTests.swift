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
        #expect(model.activeJobId == "j2")
    }

    // MARK: - プロジェクト台帳・ジョブ作成（USL-77）

    @Test func didCreateJobAddsProjectAndNavigates() {
        let model = AppModel(launcher: MockSidecarLauncher())
        model.didCreateJob(
            CreateJobResponse(jobId: "j1", projectId: "p1", status: .queued),
            title: "lecture",
            sourcePath: "/Movies/lecture.mp4"
        )

        #expect(model.projects.count == 1)
        #expect(model.projects.first?.id == "p1")
        #expect(model.projects.first?.title == "lecture")
        #expect(model.activeJobId == "j1")
        #expect(model.selection == .processing)
        // サイドバーの最近一覧にも反映され、Finder 用パスを引ける。
        #expect(model.recentProjects.first?.jobId == "j1")
        #expect(model.sourcePath(for: "p1") == "/Movies/lecture.mp4")
    }

    @Test func didCreateJobDeduplicatesByProjectKeepingNewestFirst() {
        let model = AppModel(launcher: MockSidecarLauncher())
        model.didCreateJob(CreateJobResponse(jobId: "j1", projectId: "pA", status: .queued), title: "A", sourcePath: "/a.mp4")
        model.didCreateJob(CreateJobResponse(jobId: "j2", projectId: "pB", status: .queued), title: "B", sourcePath: "/b.mp4")
        model.didCreateJob(CreateJobResponse(jobId: "j3", projectId: "pA", status: .running), title: "A2", sourcePath: "/a2.mp4")

        #expect(model.projects.count == 2)
        #expect(model.projects.first?.id == "pA") // 再作成で先頭へ
        #expect(model.projects.first?.title == "A2")
        #expect(model.sourcePath(for: "pA") == "/a2.mp4")
    }

    @Test func openProjectRowRunningNavigatesToProcessingWithJobId() {
        let model = AppModel(launcher: MockSidecarLauncher())
        model.didCreateJob(CreateJobResponse(jobId: "j1", projectId: "p1", status: .running), title: "t", sourcePath: "/t.mp4")
        model.selection = .library // いったん別画面想定

        let row = ProjectRowData(id: "p1", title: "t", duration: 0, sourceLanguage: nil, updatedAt: .init(timeIntervalSince1970: 0), state: .running)
        model.open(row)
        #expect(model.selection == .processing)
        #expect(model.activeJobId == "j1")
    }

    @Test func openProjectRowDoneNavigatesToLibrary() {
        let model = AppModel(launcher: MockSidecarLauncher())
        let row = ProjectRowData(id: "pX", title: "完了", duration: 10, sourceLanguage: "英語", updatedAt: .init(timeIntervalSince1970: 0), state: .done)
        model.open(row)
        #expect(model.selection == .library) // 完了 → プレーヤー（Library 配下 / USL-79）
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
