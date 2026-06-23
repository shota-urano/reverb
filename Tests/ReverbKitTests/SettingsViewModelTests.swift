import Testing
import Foundation
@testable import ReverbKit

/// 設定画面ロジック（USL-80）の検証。
/// 既定反映・保存値復帰・依存ゲート・保存/既定復帰・失敗時挙動を対象にする。
@Suite @MainActor struct SettingsViewModelTests {

    private func makeVM(
        repo: StubModelRepository = StubModelRepository(),
        store: any SettingsStore = InMemorySettingsStore()
    ) -> SettingsViewModel {
        SettingsViewModel(modelRepository: repo, store: store)
    }

    // MARK: - 読込・既定反映

    @Test func loadAppliesBackendDefaults() async {
        let vm = makeVM()
        await vm.load()

        #expect(vm.phase == .ready)
        #expect(vm.sttModel == STTCatalog.defaultModel) // large-v3 既定（ルール7）
        #expect(vm.translateModel == "qwen3:30b")       // /models の default
        #expect(vm.selectedSpeakerId == "13-0")          // /speakers の default
        #expect(vm.japaneseVolume == 1.0)                // 確定初期値（ルール4）
        #expect(vm.originalVolume == 0.08)
        #expect(vm.translationModels == ["qwen3:30b", "gemma3:27b"])
        #expect(vm.speakers.count == 2)
    }

    @Test func loadAppliesSavedSettingsWhenValid() async {
        let saved = JobSettings(
            stt: STTSettings(model: "turbo", language: nil),
            translate: TranslateSettings(model: "gemma3:27b"),
            tts: TTSSettings(speakerId: 11, styleId: 0),
            mix: MixSettings(jaVolume: 0.9, originalVolume: 0.12)
        )
        let vm = makeVM(store: InMemorySettingsStore(initial: saved))
        await vm.load()

        #expect(vm.sttModel == "turbo")
        #expect(vm.translateModel == "gemma3:27b")
        #expect(vm.selectedSpeakerId == "11-0")
        #expect(vm.japaneseVolume == 0.9)
        #expect(vm.originalVolume == 0.12)
    }

    @Test func loadIgnoresSavedValuesNotInCurrentLists() async {
        // 保存値のモデル/話者が現在の一覧に無い場合は既定を保つ（入れ替えに強い）。
        let saved = JobSettings(
            stt: STTSettings(model: "tiny", language: nil),       // 固定肢に無い
            translate: TranslateSettings(model: "missing-model"), // /models に無い
            tts: TTSSettings(speakerId: 999, styleId: 0),         // /speakers に無い
            mix: MixSettings(jaVolume: 0.5, originalVolume: 0.2)
        )
        let vm = makeVM(store: InMemorySettingsStore(initial: saved))
        await vm.load()

        #expect(vm.sttModel == STTCatalog.defaultModel)
        #expect(vm.translateModel == "qwen3:30b")
        #expect(vm.selectedSpeakerId == "13-0")
        // 音量は範囲内ならそのまま採用される。
        #expect(vm.japaneseVolume == 0.5)
        #expect(vm.originalVolume == 0.2)
    }

    // MARK: - 依存ゲート（screens.md §4「未接続時は該当設定を無効化」）

    @Test func dependencyGatingDisablesUnavailableSections() async {
        var repo = StubModelRepository()
        repo.healthResponse = HealthResponse(
            status: "ok", version: "0.6.0",
            dependencies: DependencyStatus(ffmpeg: true, mlxWhisper: false, ollama: false, tts: false)
        )
        // 該当エンジンが落ちていると /models /speakers も失敗しうる。
        repo.modelsError = .invalidResponse
        repo.speakersError = .invalidResponse
        let vm = makeVM(repo: repo)
        await vm.load()

        #expect(vm.phase == .ready) // health が取れれば画面は出す（失敗にしない）
        #expect(vm.sttAvailable == false)
        #expect(vm.translateAvailable == false)
        #expect(vm.ttsAvailable == false)
        #expect(vm.translationModels.isEmpty)
        #expect(vm.speakers.isEmpty)
        #expect(vm.canSave == false) // 完全な設定を作れないので保存不可
    }

    @Test func modelsFailureLeavesScreenUsableButGated() async {
        var repo = StubModelRepository()
        repo.modelsError = .invalidResponse // Ollama 接続表示だが一覧取得に失敗
        let vm = makeVM(repo: repo)
        await vm.load()

        #expect(vm.phase == .ready)
        #expect(vm.translationModels.isEmpty)
        #expect(vm.translateAvailable == false)
        #expect(vm.ttsAvailable == true) // 話者は取得できている
        #expect(vm.canSave == false)
    }

    // MARK: - 保存

    @Test func saveWritesCurrentFormToStore() async {
        let store = InMemorySettingsStore()
        let vm = makeVM(store: store)
        await vm.load()

        vm.setSTTModel("turbo")
        vm.setTranslateModel("gemma3:27b")
        vm.setSpeaker(id: "11-0")
        vm.setJapaneseVolume(0.95)
        vm.setOriginalVolume(0.1)
        #expect(vm.canSave == true)
        vm.save()

        #expect(vm.didSave == true)
        let saved = store.load()
        #expect(saved?.stt.model == "turbo")
        #expect(saved?.stt.language == nil) // 自動判定（MVP）
        #expect(saved?.translate.model == "gemma3:27b")
        #expect(saved?.tts.speakerId == 11)
        #expect(saved?.tts.styleId == 0)
        #expect(saved?.mix.jaVolume == 0.95)
        #expect(saved?.mix.originalVolume == 0.1)
    }

    @Test func editingClearsDidSaveFlag() async {
        let vm = makeVM()
        await vm.load()
        vm.save()
        #expect(vm.didSave == true)
        vm.setJapaneseVolume(0.7)
        #expect(vm.didSave == false)
    }

    @Test func settersRejectValuesNotInCurrentLists() async {
        // 一覧に無いモデル/話者は採用しない（不正設定の保存・送信を防ぐ・setSTTModel と同じ不変条件）。
        let vm = makeVM()
        await vm.load()

        vm.setTranslateModel("missing-model")
        #expect(vm.translateModel == "qwen3:30b") // 既定のまま

        vm.setSpeaker(id: "999-0")
        #expect(vm.selectedSpeakerId == "13-0") // 既定のまま

        vm.setSTTModel("tiny")
        #expect(vm.sttModel == STTCatalog.defaultModel)

        // 妥当な値・空（未選択）は受け付ける。
        vm.setTranslateModel("gemma3:27b")
        #expect(vm.translateModel == "gemma3:27b")
        vm.setSpeaker(id: "11-0")
        #expect(vm.selectedSpeakerId == "11-0")
        vm.setTranslateModel("")
        #expect(vm.translateModel == "")
    }

    @Test func setVolumeClampsToUnitRange() async {
        let vm = makeVM()
        await vm.load()
        vm.setJapaneseVolume(1.5)
        vm.setOriginalVolume(-0.2)
        #expect(vm.japaneseVolume == 1.0)
        #expect(vm.originalVolume == 0.0)
    }

    // MARK: - 既定値に戻す

    @Test func resetToDefaultsDiscardsSavedAndRestoresBackendDefaults() async {
        let saved = JobSettings(
            stt: STTSettings(model: "turbo", language: nil),
            translate: TranslateSettings(model: "gemma3:27b"),
            tts: TTSSettings(speakerId: 11, styleId: 0),
            mix: MixSettings(jaVolume: 0.9, originalVolume: 0.2)
        )
        let store = InMemorySettingsStore(initial: saved)
        let vm = makeVM(store: store)
        await vm.load()
        #expect(vm.sttModel == "turbo") // 保存値が反映済み

        await vm.resetToDefaults()

        #expect(vm.sttModel == STTCatalog.defaultModel)
        #expect(vm.translateModel == "qwen3:30b")
        #expect(vm.selectedSpeakerId == "13-0")
        #expect(vm.japaneseVolume == 1.0)
        #expect(vm.originalVolume == 0.08)
        #expect(vm.didSave == false)
        // 反映のみで保存はしない（保存値は明示的な「保存」まで消さない設計だが、
        // resetToDefaults は applySaved=false で再読込するだけ）。
        #expect(store.load() != nil)
    }

    // MARK: - 失敗時

    @Test func loadWithoutRepositoryFails() async {
        let vm = SettingsViewModel(modelRepository: nil, store: InMemorySettingsStore())
        await vm.load()
        if case .failed = vm.phase {} else {
            Issue.record("phase should be failed when not connected")
        }
        #expect(vm.canSave == false)
    }

    @Test func healthFailureFailsLoad() async {
        var repo = StubModelRepository()
        repo.healthError = .invalidResponse
        let vm = makeVM(repo: repo)
        await vm.load()
        if case .failed = vm.phase {} else {
            Issue.record("phase should be failed when /health fails")
        }
    }
}
