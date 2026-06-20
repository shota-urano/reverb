import Foundation
import Observation

/// アプリ全体の状態とサイドカー接続ライフサイクルを束ねる中核モデル。
///
/// View は描画と操作通知のみを担い、状態取得は Repository 経由でこのモデルが行う（ルール3）。
/// 画面遷移中もサイドバー選択・最近一覧・ローカル状態を維持する（screens.md 共通ナビ）。
@MainActor
@Observable
public final class AppModel {
    /// サイドカー接続状態。
    public enum Connection: Equatable {
        case idle
        case launching
        case ready
        case failed(String)
    }

    // MARK: - 公開状態

    public var connection: Connection = .idle
    public var selection: SidebarSection = .library

    /// ライブラリが管理するプロジェクト一覧（design-system ProjectRow 用 / screens.md §1）。
    /// 一覧取得 API は未定義のため、セッション内で `POST /jobs` したものをローカル保持する
    /// （永続化は 09-data-model の backend スコープ）。新しい順。
    public var projects: [ProjectRowData] { records.map(\.row) }

    /// サイドバー「最近のプロジェクト」（design-system §5.1）。projects から派生し一覧と一致させる。
    public var recentProjects: [RecentProject] {
        records.prefix(8).map {
            RecentProject(
                id: $0.row.id,
                title: $0.row.title,
                updatedAt: $0.row.updatedAt,
                state: $0.row.state,
                jobId: $0.jobId,
                thumbnailPath: $0.row.thumbnailPath
            )
        }
    }

    /// 処理中／プレーヤー画面が対象とするジョブ。行選択・新規作成で設定し、各画面（USL-78/79）が消費する。
    public private(set) var activeJobId: String?

    /// アクティブジョブのプロジェクト概要（タイトル・再生時間・言語ペア）。処理中画面のヘッダ表示に使う。
    /// 一覧取得 API は未定義のため、セッション内台帳から引く（永続化は 09-data-model の backend スコープ）。
    public var activeProject: ProjectRowData? {
        guard let activeJobId else { return nil }
        return records.first { $0.jobId == activeJobId }?.row
    }

    /// 依存エンジンの可用性（LocalOnlyStatus の表示判定に使う）。
    public private(set) var health: HealthResponse?

    /// 接続後に構築される Repository。各画面 ViewModel はここから受け取る。
    public private(set) var jobRepository: (any JobRepository)?
    public private(set) var modelRepository: (any ModelRepository)?

    // MARK: - 依存

    private let launcher: any SidecarLauncher
    private let clientFactory: @Sendable (URL) -> any BackendClient
    private var client: (any BackendClient)?
    /// 起動世代。再接続時に古いプロセスの終了通知が新シーケンスを汚染しないよう識別する。
    private var launchGeneration = 0
    /// プロジェクトのローカル台帳（行表示に加え、遷移に必要な jobId・元動画パスを保持）。
    private var records: [ProjectRecord] = []

    /// ライブラリのローカル台帳1件。行表示用 `ProjectRowData` と、遷移・Finder 表示に要る補助情報を束ねる。
    private struct ProjectRecord {
        var row: ProjectRowData
        let jobId: String
        let sourcePath: String
    }

    /// - Parameters:
    ///   - launcher: サイドカー起動境界。
    ///   - clientFactory: ハンドシェイクで得た baseURL から BackendClient を生成する。
    ///     既定は HTTPBackendClient（baseURL はハードコードしない / §3.1）。
    public init(
        launcher: any SidecarLauncher,
        clientFactory: @escaping @Sendable (URL) -> any BackendClient = { HTTPBackendClient(baseURL: $0) }
    ) {
        self.launcher = launcher
        self.clientFactory = clientFactory
    }

    // MARK: - ライフサイクル

    /// サイドカーを起動し、ハンドシェイク → /health 確認まで行って UI を有効化する（§3.1）。
    public func start() async {
        guard connection != .launching, connection != .ready else { return }
        connection = .launching
        launchGeneration += 1
        let generation = launchGeneration
        do {
            let handshake = try await launcher.launch { [weak self] status in
                // 予期せぬ終了（§3.2）。MainActor に戻して状態を反映する。
                Task { @MainActor [weak self] in
                    self?.handleUnexpectedTermination(status: status, generation: generation)
                }
            }
            let client = clientFactory(handshake.baseURL)
            self.client = client
            self.jobRepository = DefaultJobRepository(client: client)
            let modelRepository = DefaultModelRepository(client: client)
            self.modelRepository = modelRepository

            // /health 成功を確認してから ready にする（§3.1 step 4）。
            self.health = try await modelRepository.health()
            connection = .ready
        } catch {
            // launch 成功後（/health 失敗等）に失敗した場合も、サイドカーを停止し参照を解放する。
            // 放置するとバックエンドプロセスが残留し、次の start() で多重起動になりうる。
            await launcher.terminate()
            client = nil
            jobRepository = nil
            modelRepository = nil
            health = nil
            connection = .failed(describe(error))
        }
    }

    /// アプリ終了時の安全停止（§3.2）。/shutdown → プロセス終了。
    public func shutdown() async {
        await client?.shutdown()
        await launcher.terminate()
        connection = .idle
        client = nil
        jobRepository = nil
        modelRepository = nil
    }

    /// 接続失敗・予期せぬ終了からの再接続。古いプロセスを確実に停止してから起動し直す。
    public func retry() async {
        await shutdown()
        await start()
    }

    /// 最新のヘルスを取り直す（設定画面の依存エンジン表示などから利用）。
    public func refreshHealth() async {
        guard let modelRepository else { return }
        if let health = try? await modelRepository.health() {
            self.health = health
        }
    }

    // MARK: - ナビゲーション

    /// 最近のプロジェクト行を選択したときの遷移（screens.md 共通ナビ）。
    public func open(_ project: RecentProject) {
        activeJobId = project.jobId
        selection = project.destination
    }

    /// ライブラリ一覧の行を開く（screens.md §1）。完了はプレーヤー（Library 配下 / USL-79）、
    /// それ以外は処理中画面へ。jobId は台帳から引いて activeJobId に載せる。
    public func open(_ project: ProjectRowData) {
        activeJobId = records.first { $0.row.id == project.id }?.jobId
        selection = (project.state == .done) ? .library : .processing
    }

    /// 新規ジョブ作成後、一覧へ追加し処理中画面へ遷移する（screens.md §1 / 08 §3）。
    /// 同一 projectId は重複させず、新しいものを先頭に置く。
    public func didCreateJob(_ response: CreateJobResponse, title: String, sourcePath: String) {
        let row = ProjectRowData(
            id: response.projectId,
            title: title,
            duration: 0,
            sourceLanguage: nil,
            updatedAt: Date(),
            state: response.status
        )
        records.removeAll { $0.row.id == response.projectId }
        records.insert(ProjectRecord(row: row, jobId: response.jobId, sourcePath: sourcePath), at: 0)
        activeJobId = response.jobId
        selection = .processing
    }

    /// 行の「…」→ Finder 表示に使う元動画パス（セッション内で作成したもののみ取得できる）。
    public func sourcePath(for projectId: String) -> String? {
        records.first { $0.row.id == projectId }?.sourcePath
    }

    /// 処理中画面からライブラリへ戻る導線（キャンセル・失敗後 / screens.md §2）。
    public func returnToLibrary() {
        selection = .library
    }

    /// 完了したジョブをプレーヤーで開く（screens.md §2 done）。
    /// プレーヤーはライブラリ配下（USL-79）のため、現状はライブラリへ遷移して再生導線に委ねる。
    public func openCompletedJob() {
        selection = .library
    }

    /// ジョブ進行に応じて台帳の状態を更新する（処理中画面が完了/失敗/キャンセルを反映）。
    /// 一覧・最近のプロジェクトの状態表示を実態に合わせる。タイトル・元動画パスは保持する。
    /// - Parameter duration: 完了時に判明する再生時間（成果物由来）。nil なら既存値を保つ。
    public func updateJobState(jobId: String, to state: JobState, duration: Double? = nil) {
        guard let index = records.firstIndex(where: { $0.jobId == jobId }) else { return }
        let old = records[index].row
        records[index].row = ProjectRowData(
            id: old.id,
            title: old.title,
            detail: old.detail,
            duration: duration ?? old.duration,
            sourceLanguage: old.sourceLanguage,
            targetLanguage: old.targetLanguage,
            updatedAt: Date(),
            state: state,
            sourceMissing: old.sourceMissing,
            thumbnailPath: old.thumbnailPath
        )
    }

    // MARK: - Private

    private func handleUnexpectedTermination(status: Int32, generation: Int) {
        // 古い起動世代の通知は破棄する（再接続中の状態汚染を防ぐ）。
        guard generation == launchGeneration else { return }
        // ready だった場合のみ失敗に落とす（terminate() 経由の正常終了は通知しない）。
        guard connection == .ready || connection == .launching else { return }
        connection = .failed("バックエンドが予期せず終了しました（コード \(status)）")
        client = nil
        jobRepository = nil
        modelRepository = nil
    }

    private func describe(_ error: Error) -> String {
        switch error {
        case let backend as BackendError:
            return backend.localizedDescription
        case let sidecar as SidecarError:
            return Self.describe(sidecar)
        default:
            return error.localizedDescription
        }
    }

    private static func describe(_ error: SidecarError) -> String {
        switch error {
        case .notConfigured:
            return "バックエンドの起動コマンドが未設定です"
        case let .launchFailed(detail):
            return "バックエンドの起動に失敗しました: \(detail)"
        case .handshakeTimeout:
            return "バックエンドの起動応答がタイムアウトしました"
        case .handshakeUnavailable:
            return "バックエンドの起動応答を取得できませんでした"
        case let .invalidHandshake(detail):
            return "バックエンドの起動応答が不正です: \(detail)"
        }
    }
}
