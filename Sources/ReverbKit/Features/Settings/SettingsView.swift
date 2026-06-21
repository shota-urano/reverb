import SwiftUI

/// 設定画面（screens.md §4 / 08 §6）。
///
/// 処理品質（STT）・翻訳モデル・TTS 話者・再生時の初期音量を編集し、次回以降の `POST /jobs`
/// に渡す既定設定として保存する。状態取得・保存は ViewModel（Repository / SettingsStore 経由）に
/// 委ね、View は描画と操作通知に徹する（ルール3）。モデル名・話者は API から取得し固定しない（ルール5,6）。
public struct SettingsView: View {
    /// 接続状態・Repository の供給元。
    private let model: AppModel
    @State private var viewModel: SettingsViewModel

    public init(model: AppModel) {
        self.model = model
        _viewModel = State(wrappedValue: SettingsViewModel(modelRepository: model.modelRepository))
    }

    public var body: some View {
        ScreenScaffold(title: "設定") {
            content
        }
        .task {
            await viewModel.load()
        }
    }

    @ViewBuilder
    private var content: some View {
        switch viewModel.phase {
        case .loading:
            loadingState
        case .failed(let error):
            failureState(error)
        case .ready:
            readyForm
        }
    }

    private var loadingState: some View {
        HStack(spacing: 12) {
            ProgressView().controlSize(.small)
            Text("設定を読み込んでいます…")
                .font(.body)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("設定を読み込んでいます")
    }

    private func failureState(_ error: BackendErrorBody) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Label {
                Text("設定を読み込めません").font(.title3.weight(.semibold))
            } icon: {
                Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(StatusRole.error.color)
            }
            Text(error.message)
                .font(.body)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            Button("再試行") {
                Task { await viewModel.load() }
            }
            .buttonStyle(.borderedProminent)
            .keyboardShortcut(.defaultAction)
        }
        .padding(20)
        .frame(maxWidth: 560, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 10).fill(ReverbTheme.Palette.underPageBackground))
        .accessibilityElement(children: .combine)
    }

    // MARK: - フォーム本体

    private var readyForm: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: ReverbTheme.Metrics.sectionSpacing) {
                transcriptionSection
                translationSection
                ttsSection
                volumeSection
                dependencySection
                scopeNote
                actions
            }
            .frame(maxWidth: 640, alignment: .leading)
            .padding(.bottom, 8)
        }
    }

    // MARK: - 文字起こし

    private var transcriptionSection: some View {
        SettingsSection(title: "文字起こし", systemImage: "waveform") {
            settingRow(
                label: "STT モデル",
                disabled: !viewModel.sttAvailable,
                disabledNote: "mlx-whisper が未接続のため変更できません。"
            ) {
                Picker("STT モデル", selection: sttBinding) {
                    ForEach(viewModel.sttOptions) { option in
                        Text(option.displayName).tag(option.model)
                    }
                }
                .labelsHidden()
                .pickerStyle(.menu)
                .frame(maxWidth: 320, alignment: .leading)
                .disabled(!viewModel.sttAvailable)
                .accessibilityLabel("STT モデル")
            }

            // 言語: MVP は Whisper 自動判定（明示指定は将来拡張・08 §6）。
            settingRow(label: "言語", disabled: false) {
                Label("自動判定（Whisper）", systemImage: "globe")
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .accessibilityLabel("言語 自動判定")
            }
        }
    }

    // MARK: - 翻訳

    private var translationSection: some View {
        SettingsSection(title: "翻訳", systemImage: "character.book.closed") {
            settingRow(
                label: "翻訳モデル",
                disabled: !viewModel.translateAvailable,
                disabledNote: "Ollama が未接続のため変更できません。"
            ) {
                if viewModel.translationModels.isEmpty {
                    unavailablePlaceholder("翻訳モデル")
                } else {
                    Picker("翻訳モデル", selection: translateBinding) {
                        ForEach(viewModel.translationModels, id: \.self) { name in
                            Text(name).tag(name)
                        }
                    }
                    .labelsHidden()
                    .pickerStyle(.menu)
                    .frame(maxWidth: 320, alignment: .leading)
                    .disabled(!viewModel.translateAvailable)
                    .accessibilityLabel("翻訳モデル")
                }
            }
        }
    }

    // MARK: - 音声合成

    private var ttsSection: some View {
        SettingsSection(title: "音声合成", systemImage: "speaker.wave.2") {
            settingRow(
                label: "話者",
                disabled: !viewModel.ttsAvailable,
                disabledNote: "VOICEVOX が未接続のため変更できません。"
            ) {
                if viewModel.speakers.isEmpty {
                    unavailablePlaceholder("話者")
                } else {
                    Picker("話者", selection: speakerBinding) {
                        ForEach(viewModel.speakers) { speaker in
                            Text(speaker.name).tag(speaker.id)
                        }
                    }
                    .labelsHidden()
                    .pickerStyle(.menu)
                    .frame(maxWidth: 320, alignment: .leading)
                    .disabled(!viewModel.ttsAvailable)
                    .accessibilityLabel("話者")
                }
            }
        }
    }

    // MARK: - 再生時の音量

    private var volumeSection: some View {
        SettingsSection(title: "再生時の音量", systemImage: "slider.horizontal.3") {
            Text("初期値は日本語 100% / 元音声 8%。再生中にも調整できます。")
                .font(.callout)
                .foregroundStyle(.secondary)
            AudioBalanceControl(
                japaneseVolume: Binding(
                    get: { viewModel.japaneseVolume },
                    set: { viewModel.setJapaneseVolume($0) }
                ),
                originalVolume: Binding(
                    get: { viewModel.originalVolume },
                    set: { viewModel.setOriginalVolume($0) }
                )
            )
            .frame(maxWidth: 420, alignment: .leading)
        }
    }

    // MARK: - 依存エンジン

    private var dependencySection: some View {
        SettingsSection(title: "依存エンジン", systemImage: "bolt.horizontal") {
            if let dependencies = viewModel.health?.dependencies {
                DependencyStatusList(dependencies: dependencies)
                Text("未接続のエンジンは、起動・確認のうえで再読込してください。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else {
                Text("依存エンジンの状態を取得できませんでした。")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
        }
    }

    /// 既存プロジェクトへ自動適用しないことの明示（screens.md §4 / 09 §4）。
    private var scopeNote: some View {
        Label(
            "設定は次回以降の処理に適用されます。既存プロジェクトには自動適用されません。",
            systemImage: "info.circle"
        )
        .font(.callout)
        .foregroundStyle(.secondary)
        .accessibilityElement(children: .combine)
    }

    // MARK: - 操作

    private var actions: some View {
        HStack(spacing: 12) {
            Button("保存") {
                viewModel.save()
            }
            .buttonStyle(.borderedProminent)
            .keyboardShortcut("s", modifiers: .command)
            .disabled(!viewModel.canSave)
            .accessibilityHint("現在の設定を次回以降の処理の既定として保存します")

            Button("既定値に戻す") {
                Task { await viewModel.resetToDefaults() }
            }
            .accessibilityHint("バックエンドの既定値を再取得してフォームに反映します")

            if viewModel.didSave {
                Label("保存しました", systemImage: "checkmark.circle.fill")
                    .font(.callout)
                    .foregroundStyle(StatusRole.success.color)
                    .accessibilityElement(children: .combine)
                    .transition(.opacity)
            }
            Spacer(minLength: 0)
        }
        .animation(.default, value: viewModel.didSave)
    }

    /// 一覧が取得できないとき（該当エンジン未接続）に Picker の代わりに出す無効プレースホルダ。
    /// 空一覧の Picker を描かないことで選択不一致の警告を避ける。
    private func unavailablePlaceholder(_ label: String) -> some View {
        Text("選択できません")
            .font(.body)
            .foregroundStyle(.secondary)
            .frame(maxWidth: 320, alignment: .leading)
            .accessibilityLabel("\(label) 選択できません")
    }

    // MARK: - バインディング

    private var sttBinding: Binding<String> {
        Binding(get: { viewModel.sttModel }, set: { viewModel.setSTTModel($0) })
    }
    private var translateBinding: Binding<String> {
        Binding(get: { viewModel.translateModel }, set: { viewModel.setTranslateModel($0) })
    }
    private var speakerBinding: Binding<String> {
        Binding(get: { viewModel.selectedSpeakerId }, set: { viewModel.setSpeaker(id: $0) })
    }

    // MARK: - 行レイアウト

    /// ラベル＋コントロールの1行。未接続時は補足説明を添えて無効を伝える（色だけに依存しない・§7）。
    @ViewBuilder
    private func settingRow<Control: View>(
        label: String,
        disabled: Bool,
        disabledNote: String? = nil,
        @ViewBuilder control: () -> Control
    ) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline, spacing: 16) {
                Text(label)
                    .font(.body.weight(.medium))
                    .frame(width: 110, alignment: .leading)
                control()
            }
            if disabled, let disabledNote {
                Text(disabledNote)
                    .font(.caption)
                    .foregroundStyle(StatusRole.warning.color)
                    .padding(.leading, 126)
            }
        }
    }
}

/// 設定セクション（見出し＋区切り線＋内容）。リスト/フォームは影でなく区切り線で整理する（§4）。
private struct SettingsSection<Content: View>: View {
    let title: String
    let systemImage: String
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: ReverbTheme.Metrics.elementSpacing) {
            Label(title, systemImage: systemImage)
                .font(.title3.weight(.semibold))
                .accessibilityAddTraits(.isHeader)
            Divider()
            content
        }
    }
}
