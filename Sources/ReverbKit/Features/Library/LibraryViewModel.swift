import Foundation
import Observation

/// ライブラリ画面のロジック（screens.md §1 / 08 §3）。
///
/// View は描画と操作通知のみを担い、ジョブ作成は Repository 経由でここが行う（ルール3）。
/// 動画選択・ドロップで受け取った URL を検証し、`POST /jobs` を投げて結果を返す。
/// ナビゲーションと一覧保持は AppModel（遷移ハブ）に委ねる。
@MainActor
@Observable
public final class LibraryViewModel {
    /// ジョブ作成中（UI のオーバーレイ・操作無効化に使う）。
    public private(set) var isCreating = false
    /// 作成失敗・非対応形式の理由（アラート表示）。nil でアラート非表示。
    public var errorMessage: String?
    /// 直近に試した動画パス（作成失敗時に入力を保持する / screens.md §1「作成失敗」）。
    public private(set) var lastAttemptedPath: String?

    private let jobRepository: (any JobRepository)?
    /// 設定画面（USL-80）が保存した既定設定の読込元。未保存なら nil を返し、バックエンド既定を使う。
    private let settingsStore: any SettingsStore

    /// - Parameters:
    ///   - jobRepository: ジョブ作成境界。接続前は nil（このとき作成は失敗として扱う）。
    ///   - settingsStore: 既定設定の保存域（設定画面で保存した値を `POST /jobs` に渡す）。
    public init(
        jobRepository: (any JobRepository)?,
        settingsStore: any SettingsStore = UserDefaultsSettingsStore()
    ) {
        self.jobRepository = jobRepository
        self.settingsStore = settingsStore
    }

    /// 受け取った動画を検証して `POST /jobs` を投げる。
    /// 成功時はレスポンスを返し（呼び出し側が遷移）、失敗時は nil＋errorMessage を設定する。
    /// - Note: 設定画面（USL-80）で保存した既定設定があればそれを渡す。未保存なら nil で
    ///   バックエンド既定（確定初期値）に委ねる。
    public func submit(videoURL: URL) async -> CreateJobResponse? {
        guard !isCreating else { return nil } // 作成中の二重投入を防ぐ（ドロップ領域は作成中も入力を受け得る）。
        guard Self.isSupported(videoURL) else {
            lastAttemptedPath = videoURL.path
            errorMessage = "MP4 形式の動画を選択してください。"
            return nil
        }
        guard let jobRepository else {
            lastAttemptedPath = videoURL.path
            errorMessage = "バックエンドに接続していません。再接続してからお試しください。"
            return nil
        }

        isCreating = true
        lastAttemptedPath = videoURL.path
        defer { isCreating = false }

        do {
            let response = try await jobRepository.createJob(
                videoPath: videoURL.path,
                settings: settingsStore.load()
            )
            lastAttemptedPath = nil
            errorMessage = nil
            return response
        } catch is CancellationError {
            return nil // キャンセルは握り潰さず、エラー表示もしない。
        } catch {
            errorMessage = Self.describe(error)
            return nil
        }
    }

    /// アラートを閉じる。
    public func dismissError() {
        errorMessage = nil
    }

    // MARK: - 純粋ヘルパ（テスト対象）

    /// 対応形式か（MVP は MP4 のみ・大文字小文字を無視 / screens.md §1「MP4に対応」）。
    public static func isSupported(_ url: URL) -> Bool {
        url.pathExtension.lowercased() == "mp4"
    }

    /// プロジェクトの初期タイトル（拡張子を除いたファイル名）。
    public static func projectTitle(from url: URL) -> String {
        url.deletingPathExtension().lastPathComponent
    }

    private static func describe(_ error: Error) -> String {
        if let backend = error as? BackendError {
            return backend.localizedDescription
        }
        return error.localizedDescription
    }
}
