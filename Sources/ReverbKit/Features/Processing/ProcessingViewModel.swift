import Foundation
import Observation

/// 処理中画面のロジック（screens.md §2 / 08 §4）。
///
/// 進捗は **バックエンドの値をそのまま表示**し、UI 側で工程の重みを再計算しない（ルール3 / §4）。
/// 取得方針は仕様どおり **SSE 優先・ポーリングへフォールバック**:
///  1. まず `GET /jobs/{id}` で完全なスナップショット（status・error 含む）を取り、即座に画面を埋める。
///  2. 続いて `GET /jobs/{id}/events`（SSE）で進捗を更新する。
///  3. SSE が終了/失敗したら `GET /jobs/{id}` のポーリングへ切り替え、終了状態まで追う。
///
/// SSE は `progress`/`done` のみを配信し、`failed`/`canceled` と `error` は載らない（01-architecture §4.2）。
/// そのため終了状態の確定は常に `GET /jobs/{id}` に依拠する。
@MainActor
@Observable
public final class ProcessingViewModel {
    /// ジョブ全体状態。未取得時は queued 相当（「処理を準備しています」）。
    public private(set) var status: JobState = .queued
    /// 現在の工程（running 時に工程名＋短い説明を表示）。
    public private(set) var currentStage: StageName?
    /// 全体進捗 0.0〜1.0（API 値をそのまま表示）。
    public private(set) var progress: Double = 0
    /// 6工程の状態（StageProgressList が固定順に整列・欠けを補完）。
    public private(set) var stages: [StageProgress] = []
    /// 失敗時のエラーボディ（失敗工程・メッセージ）。
    public private(set) var failure: BackendErrorBody?
    /// 使用中の翻訳モデル（`/models` の既定値を表示。取得不可なら nil で非表示）。
    public private(set) var translateModel: String?
    /// キャンセル要求の送信中（ボタン二度押し防止）。
    public private(set) var isCanceling = false
    /// 再開要求の送信中（ボタン二度押し防止 / USL-116）。
    public private(set) var isResuming = false
    /// バックエンドと通信できていない（SSE もポーリングも届かない）。直近の進捗は保持したまま注意表示。
    public private(set) var connectionLost = false

    private let jobRepository: (any JobRepository)?
    private let modelRepository: (any ModelRepository)?
    /// ポーリング間隔（フォールバック時）。品質優先の長時間処理なので過剰に詰めない。
    private let pollInterval: Duration

    public init(
        jobRepository: (any JobRepository)?,
        modelRepository: (any ModelRepository)?,
        pollInterval: Duration = .seconds(1)
    ) {
        self.jobRepository = jobRepository
        self.modelRepository = modelRepository
        self.pollInterval = pollInterval
    }

    // MARK: - 派生状態（テスト対象・UI 非依存）

    /// 終了状態か（done/failed/canceled）。操作・表示の分岐に使う。
    public var isTerminal: Bool { Self.isTerminal(status) }

    public static func isTerminal(_ state: JobState) -> Bool {
        switch state {
        case .done, .failed, .canceled: return true
        case .queued, .running: return false
        }
    }

    /// キャンセル可能か（実行前〜実行中のみ）。
    public var canCancel: Bool { !isTerminal && !isCanceling }

    /// 再開可能か（失敗／キャンセル済みのみ / USL-116）。backend は done/running/queued を 409 で拒否する。
    public var canResume: Bool { (status == .failed || status == .canceled) && !isResuming }

    /// 全体進捗の百分率表示（API 値由来。UI で重みを足さない）。
    public var progressText: String { ReverbFormat.percent(progress) }

    // MARK: - 観測

    /// 対象ジョブの観測を開始する。View の `.task(id:)` から駆動され、終了状態に達するか
    /// タスクがキャンセルされるまで継続する。再試行・再表示のたびに呼び直してよい。
    public func observe(jobId: String) async {
        failure = nil
        connectionLost = false

        await loadTranslateModel()

        guard let jobRepository else {
            connectionLost = true // 未接続は黙って進めない（失敗を握り潰さない）。
            return
        }

        // 1) スナップショットで即座に画面を埋める。既に終了済みならここで確定。
        if await refresh(jobRepository, jobId) { return }
        if Task.isCancelled { return }

        // 2) SSE（低遅延）とポーリング（確実性）を並行実行する。
        //    SSE は環境によりイベントが届かないことがあるため、ポーリングを常時の
        //    更新基盤とし、SSE は届けば即時反映する上乗せとする。どちらの更新も
        //    @MainActor 上の apply 経由なので競合しない。終了状態はポーリングが確定する。
        await withTaskGroup(of: Bool.self) { group in
            group.addTask { [weak self] in
                guard let self else { return false }
                return await self.streamEvents(jobRepository, jobId)
            }
            group.addTask { [weak self] in
                guard let self else { return false }
                return await self.pollUntilTerminal(jobRepository, jobId)
            }
            // 子の戻り値は「終了状態に達したか」。SSE が done 無しで閉じても（false）
            // ポーリングは止めず継続する。どちらかが終了状態を確定したら残りを止める。
            while let reachedTerminal = await group.next() {
                if reachedTerminal {
                    group.cancelAll()
                    return
                }
            }
        }
    }

    /// キャンセルを要求する（確認ダイアログ確定後に呼ぶ / screens.md §2）。
    /// 成功時は楽観的に canceled を反映する（バックエンドも canceled に遷移する）。
    /// - Parameter jobId: 対象ジョブ（View が `activeJobId` を渡す。観測の有無に依存させない）。
    public func cancel(jobId: String) async {
        guard let jobRepository, canCancel else { return }
        isCanceling = true
        defer { isCanceling = false }
        do {
            try await jobRepository.cancel(id: jobId)
            status = .canceled
            currentStage = nil
        } catch is CancellationError {
            // 画面遷移等によるキャンセルは握り潰す。
        } catch {
            // キャンセル送信自体の失敗は理由を見せる（失敗を黙ってスキップしない）。
            failure = Self.errorBody(from: error)
        }
    }

    /// 失敗／キャンセル済みジョブを途中再開する（失敗画面の「再開」ボタンから呼ぶ / USL-116）。
    /// 成功時は終了状態を解除して queued に楽観反映し `true` を返す。呼び出し側（View）はこれを受けて
    /// 観測を貼り直し、失敗ステージ以降の再実行を完了まで追従する（jobId は据え置き）。
    /// 楽観反映で終了状態を先に解いておくことが重要: これをしないと `apply` の巻き戻しガードにより
    /// 再観測の非終了スナップショットが弾かれ、画面が失敗表示のまま固まる。
    /// 拒否（409/404）や通信失敗時は状態を変えず理由を `failure` に載せ `false` を返す（黙って握り潰さない）。
    /// - Returns: 再開要求が受理されたか（View は true のときだけ再観測を貼り直す）。
    @discardableResult
    public func resume(jobId: String) async -> Bool {
        guard let jobRepository, canResume else { return false }
        isResuming = true
        defer { isResuming = false }
        do {
            _ = try await jobRepository.resume(id: jobId)
            status = .queued // 終了状態を解除（再観測の巻き戻しガードを通す）。
            currentStage = nil
            failure = nil
            connectionLost = false
            return true
        } catch is CancellationError {
            return false // 画面遷移等によるキャンセルは握り潰す。
        } catch {
            failure = Self.errorBody(from: error) // 409/404 の理由を提示する。
            return false
        }
    }

    // MARK: - 観測の内部実装

    /// `GET /jobs/{id}/events` を購読し、進捗を反映する。`done` を観測したら true。
    /// stream が終了/失敗したら false を返し、呼び出し側がポーリングへ切り替える。
    private func streamEvents(_ repo: any JobRepository, _ jobId: String) async -> Bool {
        do {
            for try await event in repo.events(id: jobId) {
                apply(event)
                connectionLost = false
                if case .done = event { return true }
                if Task.isCancelled { return false }
            }
            return false // done 無しで終端 → ポーリングへ
        } catch is CancellationError {
            return false
        } catch {
            return false // SSE 不可 → ポーリングへ（接続不能はポーリング側で判定）
        }
    }

    /// 終了状態に達するまで一定間隔でスナップショットを取り続ける。
    /// 終了状態を確定したら true、キャンセルで打ち切ったら false。
    private func pollUntilTerminal(_ repo: any JobRepository, _ jobId: String) async -> Bool {
        while !Task.isCancelled {
            if await refresh(repo, jobId) { return true }
            do {
                try await Task.sleep(for: pollInterval)
            } catch {
                return false // キャンセル
            }
        }
        return false
    }

    /// スナップショットを1回取得して反映する。終了状態なら true。
    @discardableResult
    private func refresh(_ repo: any JobRepository, _ jobId: String) async -> Bool {
        do {
            let snapshot = try await repo.job(id: jobId)
            apply(snapshot)
            connectionLost = false
            return Self.isTerminal(snapshot.status)
        } catch is CancellationError {
            return true // 観測停止
        } catch {
            connectionLost = true // 通信不能。直近の表示は残し、ポーリングを継続する。
            return false
        }
    }

    /// 翻訳モデル名を `/models` から取得（ハードコードしない・ルール6）。失敗時は nil のまま。
    private func loadTranslateModel() async {
        guard translateModel == nil, let modelRepository else { return }
        translateModel = try? await modelRepository.translationModels().defaultModel
    }

    // MARK: - リデューサ（テスト対象）

    /// スナップショット（完全な状態）を反映する。
    /// SSE とポーリングが並走するため、終了確定後に取得済みの古い非終了
    /// スナップショットが遅れて届き得る。終了状態を巻き戻さない（USL-112）。
    func apply(_ snapshot: JobStatus) {
        if isTerminal && !Self.isTerminal(snapshot.status) { return }
        status = snapshot.status
        currentStage = snapshot.currentStage
        progress = snapshot.progress
        if !snapshot.stages.isEmpty { stages = snapshot.stages }
        failure = snapshot.error
    }

    /// SSE イベント（部分更新）を反映する。終了状態を後続の遅延イベントで巻き戻さない。
    func apply(_ event: JobEvent) {
        guard !isTerminal else { return }
        switch event {
        case .progress(let progressEvent):
            status = .running
            currentStage = progressEvent.currentStage
            progress = progressEvent.progress
            if !progressEvent.stages.isEmpty { stages = progressEvent.stages }
        case .done:
            status = .done
            currentStage = nil
            progress = 1
        }
    }

    /// 任意のエラーを表示用のエラーボディへ。API 封筒はそのまま、それ以外（通信層等）は
    /// メッセージを保って包む。cancel / resume 双方の失敗提示で共有する。
    private static func errorBody(from error: Error) -> BackendErrorBody {
        if case let BackendError.api(body, _) = error { return body }
        return BackendErrorBody(code: "REQUEST_FAILED", stage: nil, message: error.localizedDescription, retryable: true)
    }
}
