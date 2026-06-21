import Foundation
import Observation

/// 設定画面のロジック（screens.md §4 / 08 §6）。
///
/// 処理品質（STT）・翻訳モデル・TTS 話者・再生時の初期音量を編集し、次回以降の `POST /jobs`
/// に渡す既定設定としてローカル保存する（ルール3: View に処理ロジックを置かない）。
///
/// - モデル名・話者は `/models` `/speakers` から動的取得し、UI コードに固定しない（ルール5,6）。
///   既定値はバックエンドが返す値を使う。STT のみ仕様上の固定肢（[`STTCatalog`]）。
/// - 依存エンジン状態は `/health` で取得し、未接続のエンジンに紐づく設定を無効化する（screens.md §4）。
/// - 確定初期値（日本語100%/元音声8%）を初期表示・既定復帰の基準にする（ルール4）。
@MainActor
@Observable
public final class SettingsViewModel {
    /// 読込フェーズ。
    public enum LoadPhase: Equatable {
        case loading
        case ready
        case failed(BackendErrorBody)
    }

    // MARK: - 公開状態（読込）

    public private(set) var phase: LoadPhase = .loading
    /// 依存エンジンの可用性（依存セクション表示・各設定の有効/無効判定に使う）。
    public private(set) var health: HealthResponse?
    /// 翻訳モデル一覧（`/models`・ハードコードしない）。Ollama 未接続時は空。
    public private(set) var translationModels: [String] = []
    /// TTS 話者一覧（`/speakers`・ハードコードしない）。VOICEVOX 未接続時は空。
    public private(set) var speakers: [Speaker] = []
    /// STT の固定肢（large-v3 既定 / turbo）。
    public let sttOptions = STTCatalog.options

    // MARK: - フォーム選択（setter 経由で編集）

    /// STT モデル（`settings.stt.model`）。
    public private(set) var sttModel: String = STTCatalog.defaultModel
    /// 翻訳モデル（`settings.translate.model`）。
    public private(set) var translateModel: String = ""
    /// 選択中の話者（`Speaker.id` = "speakerId-styleId"）。Picker と結ぶための文字列キー。
    public private(set) var selectedSpeakerId: String = ""
    /// 日本語ゲイン初期値（確定 100% / ルール4）。
    public private(set) var japaneseVolume: Double = MixSettings.confirmedInitial.jaVolume
    /// 元音声ゲイン初期値（確定 8% / ルール4）。
    public private(set) var originalVolume: Double = MixSettings.confirmedInitial.originalVolume

    /// 直近の保存が成功したか（「保存しました」表示用）。編集・再読込でリセットする。
    public private(set) var didSave = false

    private let modelRepository: (any ModelRepository)?
    private let store: any SettingsStore

    public init(
        modelRepository: (any ModelRepository)?,
        store: any SettingsStore = UserDefaultsSettingsStore()
    ) {
        self.modelRepository = modelRepository
        self.store = store
    }

    // MARK: - 派生状態（テスト対象・UI 非依存）

    /// 言語は MVP では Whisper 自動判定（明示指定は将来拡張・08 §6）。`settings.stt.language == nil`。
    public let languageIsAutoDetect = true

    /// 文字起こし設定が使えるか（mlx-whisper 接続時のみ）。
    public var sttAvailable: Bool { health?.dependencies.mlxWhisper ?? false }
    /// 翻訳設定が使えるか（Ollama 接続かつモデルを取得できた）。
    public var translateAvailable: Bool { (health?.dependencies.ollama ?? false) && !translationModels.isEmpty }
    /// TTS 設定が使えるか（VOICEVOX 接続かつ話者を取得できた）。
    public var ttsAvailable: Bool { (health?.dependencies.voicevox ?? false) && !speakers.isEmpty }

    /// 選択中の話者（解決できなければ nil）。
    public var selectedSpeaker: Speaker? {
        speakers.first { $0.id == selectedSpeakerId }
    }

    /// 保存可能か。翻訳モデルと話者がそろって初めて完全な `JobSettings` を作れる
    /// （省略時はバックエンド既定が使われるため、部分設定は保存しない）。
    public var canSave: Bool {
        phase == .ready && !translateModel.isEmpty && selectedSpeaker != nil
    }

    // MARK: - 読込

    /// 依存状態・翻訳モデル・話者を取得し、フォームを初期化する（screens.md §4「データ取得」）。
    /// - Parameter applySaved: 保存済み設定をフォームへ反映するか（既定値復帰では false）。
    public func load(applySaved: Bool = true) async {
        phase = .loading
        didSave = false

        guard let modelRepository else {
            phase = .failed(Self.connectionError)
            return
        }

        // /health は必須（依存ゲートの根拠）。/models・/speakers は該当エンジン未接続時に
        // 失敗しうるため、取得できなければ空のまま該当設定を無効化する（失敗を握り潰さない＝健全）。
        let health: HealthResponse
        do {
            health = try await modelRepository.health()
        } catch is CancellationError {
            return
        } catch {
            phase = .failed(Self.errorBody(from: error))
            return
        }
        self.health = health

        async let modelsTask: ModelsResponse? = try? await modelRepository.translationModels()
        async let speakersTask: SpeakersResponse? = try? await modelRepository.speakers()
        let models = await modelsTask
        let speakers = await speakersTask
        if Task.isCancelled { return }

        translationModels = models?.models ?? []
        self.speakers = speakers?.speakers ?? []

        applyBackendDefaults(models: models, speakers: speakers)
        if applySaved, let saved = store.load() {
            apply(saved: saved)
        }
        phase = .ready
    }

    /// 依存エンジン状態だけを取り直す（設定変更なしに最新状態を反映したいとき）。
    public func refreshDependencies() async {
        guard let modelRepository else { return }
        if let health = try? await modelRepository.health() {
            self.health = health
        }
    }

    // MARK: - 編集（setter 経由で didSave を解除）

    public func setSTTModel(_ model: String) {
        guard STTCatalog.contains(model) else { return }
        sttModel = model
        didSave = false
    }

    public func setTranslateModel(_ model: String) {
        // 一覧に無い値は採用しない（不正な設定が保存・送信されるのを防ぐ）。空は「未選択」として許可。
        guard model.isEmpty || translationModels.contains(model) else { return }
        translateModel = model
        didSave = false
    }

    public func setSpeaker(id: String) {
        // 一覧に無い話者は採用しない（setSTTModel と同じ不変条件）。空は「未選択」として許可。
        guard id.isEmpty || speakers.contains(where: { $0.id == id }) else { return }
        selectedSpeakerId = id
        didSave = false
    }

    public func setJapaneseVolume(_ value: Double) {
        japaneseVolume = min(max(value, 0), 1)
        didSave = false
    }

    public func setOriginalVolume(_ value: Double) {
        originalVolume = min(max(value, 0), 1)
        didSave = false
    }

    // MARK: - 保存 / 既定値に戻す（screens.md §4）

    /// フォーム内容を次回以降の `POST /jobs` 既定設定としてローカル保存する。
    public func save() {
        guard let settings = currentSettings() else { return }
        store.save(settings)
        didSave = true
    }

    /// バックエンド既定値を再取得してフォームへ反映する（保存値は破棄して既定に戻す）。
    /// 反映のみで保存はしない（保存は明示的な「保存」操作に委ねる）。
    public func resetToDefaults() async {
        await load(applySaved: false)
    }

    // MARK: - 内部

    /// バックエンド既定（確定初期値）をフォームへ反映する。
    private func applyBackendDefaults(models: ModelsResponse?, speakers: SpeakersResponse?) {
        sttModel = STTCatalog.defaultModel
        translateModel = models?.defaultModel ?? translationModels.first ?? ""
        selectedSpeakerId = speakers?.defaultSpeaker.id ?? self.speakers.first?.id ?? ""
        japaneseVolume = MixSettings.confirmedInitial.jaVolume
        originalVolume = MixSettings.confirmedInitial.originalVolume
    }

    /// 保存済み設定をフォームへ反映する。現在の選択肢に存在しない値は採用せず既定を保つ
    /// （モデル/話者が入れ替わっても壊れないようにする）。
    private func apply(saved: JobSettings) {
        if STTCatalog.contains(saved.stt.model) {
            sttModel = saved.stt.model
        }
        if translationModels.contains(saved.translate.model) {
            translateModel = saved.translate.model
        }
        let savedSpeakerId = "\(saved.tts.speakerId)-\(saved.tts.styleId)"
        if speakers.contains(where: { $0.id == savedSpeakerId }) {
            selectedSpeakerId = savedSpeakerId
        }
        japaneseVolume = min(max(saved.mix.jaVolume, 0), 1)
        originalVolume = min(max(saved.mix.originalVolume, 0), 1)
    }

    /// フォームから `JobSettings` を組み立てる。完全な設定にできなければ nil。
    private func currentSettings() -> JobSettings? {
        guard let speaker = selectedSpeaker, !translateModel.isEmpty else { return nil }
        return JobSettings(
            stt: STTSettings(model: sttModel, language: nil), // 自動判定（MVP・08 §6）
            translate: TranslateSettings(model: translateModel),
            tts: TTSSettings(speakerId: speaker.speakerId, styleId: speaker.styleId),
            mix: MixSettings(jaVolume: japaneseVolume, originalVolume: originalVolume)
        )
    }

    // MARK: - エラー整形

    static let connectionError = BackendErrorBody(
        code: "NOT_CONNECTED",
        stage: nil,
        message: "バックエンドに接続していません。再接続してからお試しください。",
        retryable: true
    )

    private static func errorBody(from error: Error) -> BackendErrorBody {
        if case let BackendError.api(body, _) = error { return body }
        return BackendErrorBody(
            code: "SETTINGS_UNAVAILABLE",
            stage: nil,
            message: error.localizedDescription,
            retryable: true
        )
    }
}
