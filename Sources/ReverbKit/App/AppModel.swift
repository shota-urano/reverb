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
    public var recentProjects: [RecentProject] = []
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
        selection = project.destination
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
