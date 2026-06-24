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

    // MARK: - 起動時のライブラリ復元（USL-95）

    @Test func startRestoresPersistedProjects() async {
        var client = MockBackendClient()
        client.jobList = JobListResponse(items: [
            JobSummary(projectId: "p_new", jobId: "j_new", status: .running,
                       createdAt: "2026-06-21T10:00:00+00:00", duration: 30,
                       videoPath: "/Movies/new.mp4", language: nil, currentStage: .tts,
                       hasThumbnail: false),
            JobSummary(projectId: "p_old", jobId: "j_old", status: .done,
                       createdAt: "2026-06-19T10:00:00+00:00", duration: 12.5,
                       videoPath: "/Movies/old lecture.mp4", language: "en", currentStage: nil,
                       hasThumbnail: true),
        ])
        let model = AppModel(launcher: MockSidecarLauncher(), clientFactory: { [client] _ in client })

        await model.start()

        #expect(model.connection == .ready)
        #expect(model.libraryLoadError == nil)
        #expect(model.thumbnailProvider != nil) // 接続後にサムネイル取得境界が構築される（USL-103）
        #expect(model.projects.count == 2)
        // 新しい順を維持。タイトルは videoPath のファイル名（拡張子除く）から導出。
        #expect(model.projects.first?.id == "p_new")
        #expect(model.projects.first?.title == "new")
        #expect(model.projects.first?.state == .running)
        // hasThumbnail が行へ反映される（生成前=false / 生成済み=true）。
        #expect(model.projects.first?.thumbnailAvailable == false)
        #expect(model.projects.first?.jobId == "j_new")
        #expect(model.projects.last?.thumbnailAvailable == true)
        #expect(model.projects.last?.title == "old lecture")
        #expect(model.projects.last?.duration == 12.5)
        // 完了プロジェクトを行から開くとプレーヤー（既存導線がそのまま機能）。
        #expect(model.sourcePath(for: "p_old") == "/Movies/old lecture.mp4")
        if let row = model.projects.last {
            model.open(row)
            #expect(model.playerJobId == "j_old")
            #expect(model.selection == .library)
        }
    }

    @Test func startParsesFractionalSecondTimestamps() async {
        // backend は datetime.now(timezone.utc).isoformat()（小数秒付き）を出す。distantPast に落ちないこと。
        var client = MockBackendClient()
        client.jobList = JobListResponse(items: [
            JobSummary(projectId: "p1", jobId: "j1", status: .done,
                       createdAt: "2026-06-23T06:45:56.448757+00:00", duration: 1,
                       videoPath: "/Movies/v.mp4", language: nil, currentStage: nil),
        ])
        let model = AppModel(launcher: MockSidecarLauncher(), clientFactory: { [client] _ in client })

        await model.start()

        #expect(model.projects.count == 1)
        #expect(model.projects.first?.updatedAt != .distantPast)
        // 2026-06-23T06:45:56Z 近傍であること（小数秒が正しく解釈されている）。
        let expected = Date(timeIntervalSince1970: 1_782_197_156) // 2026-06-23T06:45:56Z
        #expect(abs((model.projects.first?.updatedAt ?? .distantPast).timeIntervalSince(expected)) < 1.0)
    }

    @Test func startKeepsConnectionWhenListFails() async {
        var client = MockBackendClient()
        client.jobsError = .invalidResponse
        let model = AppModel(launcher: MockSidecarLauncher(), clientFactory: { [client] _ in client })

        await model.start()

        // 一覧取得失敗でも接続は維持し、一覧は空・落ちない。失敗は握りつぶさず保持。
        #expect(model.connection == .ready)
        #expect(model.projects.isEmpty)
        #expect(model.libraryLoadError != nil)
    }

    @Test func restoredProjectsDeduplicateAgainstSessionCreated() async {
        // セッション内で作成済みの projectId は、再接続時の復元でも重複させずセッション側を優先する。
        var client = MockBackendClient()
        client.jobList = JobListResponse(items: [
            JobSummary(projectId: "pA", jobId: "j_remote", status: .done,
                       createdAt: "2026-06-19T10:00:00+00:00", duration: 5,
                       videoPath: "/Movies/remoteA.mp4", language: nil, currentStage: nil),
        ])
        let model = AppModel(launcher: MockSidecarLauncher(), clientFactory: { [client] _ in client })
        model.didCreateJob(CreateJobResponse(jobId: "j_session", projectId: "pA", status: .running),
                           title: "sessionA", sourcePath: "/Movies/sessionA.mp4")

        await model.start()

        #expect(model.projects.count == 1)
        #expect(model.projects.first?.title == "sessionA") // セッション側を優先
        #expect(model.sourcePath(for: "pA") == "/Movies/sessionA.mp4")
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

    // MARK: - プレーヤー遷移（USL-79）

    @Test func openDoneProjectRowOpensPlayer() {
        let model = AppModel(launcher: MockSidecarLauncher())
        model.didCreateJob(CreateJobResponse(jobId: "jD", projectId: "pD", status: .done), title: "完了", sourcePath: "/d.mp4")
        let row = ProjectRowData(id: "pD", title: "完了", duration: 10, sourceLanguage: nil, updatedAt: .init(timeIntervalSince1970: 0), state: .done)

        model.open(row)
        #expect(model.playerJobId == "jD") // library 配下でプレーヤーを最前面に
        #expect(model.activeJobId == "jD")
        #expect(model.selection == .library)
    }

    @Test func openDoneRecentProjectOpensPlayer() {
        let model = AppModel(launcher: MockSidecarLauncher())
        let done = RecentProject(id: "pR", title: "完了", updatedAt: .init(timeIntervalSince1970: 0), state: .done, jobId: "jR")
        model.open(done)
        #expect(model.playerJobId == "jR")
    }

    @Test func openRunningProjectDoesNotOpenPlayer() {
        let model = AppModel(launcher: MockSidecarLauncher())
        let running = RecentProject(id: "pr", title: "処理中", updatedAt: .init(timeIntervalSince1970: 0), state: .running, jobId: "jr")
        model.open(running)
        #expect(model.playerJobId == nil)
        #expect(model.selection == .processing)
    }

    @Test func navigatingAwayClosesPlayer() {
        let model = AppModel(launcher: MockSidecarLauncher())
        let done = RecentProject(id: "pR", title: "完了", updatedAt: .init(timeIntervalSince1970: 0), state: .done, jobId: "jR")
        model.open(done)
        #expect(model.playerJobId == "jR")

        model.selection = .settings // サイドバーで他画面へ → プレーヤーを閉じる
        #expect(model.playerJobId == nil)
    }

    @Test func closePlayerReturnsToLibraryList() {
        let model = AppModel(launcher: MockSidecarLauncher())
        let done = RecentProject(id: "pR", title: "完了", updatedAt: .init(timeIntervalSince1970: 0), state: .done, jobId: "jR")
        model.open(done)
        model.closePlayer()
        #expect(model.playerJobId == nil)
        #expect(model.selection == .library) // 一覧へ戻る
    }

    @Test func openCompletedJobOpensPlayerForActiveJob() {
        let model = AppModel(launcher: MockSidecarLauncher())
        model.didCreateJob(CreateJobResponse(jobId: "jA", projectId: "pA", status: .running), title: "t", sourcePath: "/t.mp4")
        // activeJobId = jA。処理完了後に視聴導線から開く。
        model.openCompletedJob()
        #expect(model.playerJobId == "jA")
        #expect(model.selection == .library)
    }

    // MARK: - プロジェクト削除（USL-102）

    @Test func deleteProjectRemovesFromLibraryOnSuccess() async throws {
        var client = MockBackendClient()
        client.jobList = JobListResponse(items: [
            JobSummary(projectId: "p_keep", jobId: "j_keep", status: .done,
                       createdAt: "2026-06-21T10:00:00+00:00", duration: 5,
                       videoPath: "/Movies/keep.mp4", language: nil, currentStage: nil),
            JobSummary(projectId: "p_del", jobId: "j_del", status: .done,
                       createdAt: "2026-06-20T10:00:00+00:00", duration: 8,
                       videoPath: "/Movies/del.mp4", language: nil, currentStage: nil),
        ])
        let model = AppModel(launcher: MockSidecarLauncher(), clientFactory: { [client] _ in client })
        await model.start()
        #expect(model.projects.count == 2)

        let target = try #require(model.projects.first { $0.id == "p_del" })
        try await model.deleteProject(target)

        // 成功時は台帳から除去され一覧が即時更新される。他のプロジェクトは残る。
        #expect(model.projects.count == 1)
        #expect(model.projects.first?.id == "p_keep")
    }

    @Test func deleteProjectKeepsListWhenBackendRejects() async {
        var client = MockBackendClient()
        client.jobList = JobListResponse(items: [
            JobSummary(projectId: "p_run", jobId: "j_run", status: .running,
                       createdAt: "2026-06-21T10:00:00+00:00", duration: 0,
                       videoPath: "/Movies/run.mp4", language: nil, currentStage: .translate),
        ])
        // 実行中は backend が 409 で拒否する想定。
        client.deleteError = .api(
            BackendErrorBody(code: "JOB_RUNNING", stage: nil, message: "Job is running", retryable: true),
            statusCode: 409
        )
        let model = AppModel(launcher: MockSidecarLauncher(), clientFactory: { [client] _ in client })
        await model.start()
        let target = model.projects.first!

        await #expect(throws: BackendError.self) {
            try await model.deleteProject(target)
        }
        // 失敗時は握り潰さず投げ、台帳は変更しない（一覧の不整合を起こさない）。
        #expect(model.projects.count == 1)
        #expect(model.projects.first?.id == "p_run")
    }

    @Test func deleteProjectClearsOpenPlayerForDeletedJob() async throws {
        var client = MockBackendClient()
        client.jobList = JobListResponse(items: [
            JobSummary(projectId: "p_open", jobId: "j_open", status: .done,
                       createdAt: "2026-06-21T10:00:00+00:00", duration: 5,
                       videoPath: "/Movies/open.mp4", language: nil, currentStage: nil),
        ])
        let model = AppModel(launcher: MockSidecarLauncher(), clientFactory: { [client] _ in client })
        await model.start()
        let target = try #require(model.projects.first)
        model.open(target) // プレーヤーで開いた状態にする
        #expect(model.playerJobId == "j_open")

        try await model.deleteProject(target)

        // 削除対象が開いていたら、開いた状態を解除して参照の残留を防ぐ。
        #expect(model.projects.isEmpty)
        #expect(model.playerJobId == nil)
        #expect(model.activeJobId == nil)
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
