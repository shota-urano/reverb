import SwiftUI

/// 処理中画面（screens.md §2 / 08 §4）。
///
/// 品質優先の一括処理について、全体進捗と現在工程を明確に伝える。状態取得・キャンセルは
/// ViewModel（Repository 経由）が担い、View は描画と操作通知に徹する（ルール3）。
/// 進捗は API 値をそのまま表示し、UI 側で工程の重みを再計算しない（§4）。
public struct ProcessingView: View {
    /// 遷移ハブ兼プロジェクト台帳（アクティブジョブ・概要・ナビゲーションの単一情報源）。
    private let model: AppModel
    @State private var viewModel: ProcessingViewModel
    /// 再観測トリガ（失敗後の「状態を再取得」で増やし `.task` を貼り直す）。
    @State private var observeNonce = 0
    @State private var showCancelConfirm = false

    public init(model: AppModel) {
        self.model = model
        _viewModel = State(wrappedValue: ProcessingViewModel(
            jobRepository: model.jobRepository,
            modelRepository: model.modelRepository
        ))
    }

    public var body: some View {
        ScreenScaffold(title: "処理中") {
            if let jobId = model.activeJobId {
                jobContent(jobId: jobId)
            } else {
                emptyState
            }
        }
        .task(id: ObserveKey(jobId: model.activeJobId, nonce: observeNonce)) {
            guard let jobId = model.activeJobId else { return }
            await viewModel.observe(jobId: jobId)
        }
        .onChange(of: viewModel.status) { _, newValue in
            reflectTerminalState(newValue) // 一覧・最近一覧へ完了/失敗/キャンセルを反映。
        }
        .confirmationDialog(
            "処理をキャンセルしますか？",
            isPresented: $showCancelConfirm,
            titleVisibility: .visible
        ) {
            Button("キャンセルする", role: .destructive) {
                if let jobId = model.activeJobId {
                    Task { await viewModel.cancel(jobId: jobId) }
                }
            }
            Button("続ける", role: .cancel) {}
        } message: {
            Text("ここまでの成果物は保存され、あとで再開できます。")
        }
    }

    // MARK: - 本体

    @ViewBuilder
    private func jobContent(jobId: String) -> some View {
        header
        statusSection
        if viewModel.connectionLost && !viewModel.isTerminal {
            connectionWarning
        }
        StageProgressList(stages: viewModel.stages)
        if !viewModel.isTerminal {
            localNote
        }
        actions
    }

    // MARK: - ヘッダ

    private var header: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(model.activeProject?.title ?? "処理中のプロジェクト")
                .font(.title2.weight(.semibold))
                .accessibilityAddTraits(.isHeader)

            HStack(spacing: 14) {
                metaItem(systemImage: "character.bubble", text: languagePair)
                if let duration = model.activeProject?.duration, duration > 0 {
                    metaItem(systemImage: "clock", text: ReverbFormat.timecode(duration))
                }
                if let translateModel = viewModel.translateModel {
                    metaItem(systemImage: "cpu", text: translateModel)
                }
            }
            .font(.callout)
            .foregroundStyle(.secondary)

            LocalOnlyStatus(healthy: model.health?.dependencies.allAvailable ?? false)
        }
    }

    private var languagePair: String {
        ReverbFormat.languagePair(source: model.activeProject?.sourceLanguage)
    }

    private func metaItem(systemImage: String, text: String) -> some View {
        HStack(spacing: 4) {
            Image(systemName: systemImage)
            Text(text)
        }
        .accessibilityElement(children: .combine)
    }

    // MARK: - 状態別セクション

    @ViewBuilder
    private var statusSection: some View {
        switch viewModel.status {
        case .queued:
            preparingSection
        case .running:
            runningSection
        case .done:
            terminalBanner(
                systemImage: "checkmark.circle.fill",
                role: .success,
                title: "処理が完了しました",
                detail: "日本語の吹き替えと字幕で視聴できます。"
            )
        case .failed:
            failureSection
        case .canceled:
            VStack(alignment: .leading, spacing: 10) {
                terminalBanner(
                    systemImage: "minus.circle.fill",
                    role: .neutral,
                    title: "処理をキャンセルしました",
                    detail: "ここまでの成果物は保存されています。「再開」ボタンで続きから再開できます。"
                )
                // 再開拒否（例: 削除済みで 404、競合で 409）の理由を握り潰さず提示する（USL-116）。
                // 失敗画面は failureSection が自前で出すため、canceled 経路の受け皿はここに置く。
                if let failure = viewModel.failure {
                    resumeErrorNote(failure)
                }
            }
        }
    }

    /// 再開要求が拒否されたときの理由表示（canceled バナー下に添える / USL-116）。
    private func resumeErrorNote(_ failure: BackendErrorBody) -> some View {
        Label {
            Text(failure.message)
                .font(.callout)
                .foregroundStyle(.secondary)
                .textSelection(.enabled)
        } icon: {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(StatusRole.error.color)
        }
        .accessibilityElement(children: .combine)
    }

    /// queued: まだ工程が始まっていない（不確定インジケータ）。
    private var preparingSection: some View {
        HStack(spacing: 12) {
            SlowSpinner(size: 16)
            Text("処理を準備しています")
                .font(.body)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("処理を準備しています")
    }

    /// running: 全体進捗バー＋現在工程名＋短い説明（§2）。
    private var runningSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .firstTextBaseline) {
                Text(viewModel.currentStage?.displayName ?? "処理中")
                    .font(.title3.weight(.semibold))
                Spacer()
                Text(viewModel.progressText)
                    .font(.title3.monospacedDigit())
                    .foregroundStyle(.secondary)
            }

            ProgressView(value: clampedProgress)
                .progressViewStyle(.linear)
                .tint(ReverbTheme.Palette.accent)
                .accessibilityLabel("全体進捗")
                .accessibilityValue(viewModel.progressText)

            if let caption = viewModel.currentStage?.caption {
                Text(caption)
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
        }
    }

    /// failed: 失敗工程＋error.message と再開導線（§2 / 01 §5）。
    private var failureSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label {
                Text("処理に失敗しました")
                    .font(.title3.weight(.semibold))
            } icon: {
                Image(systemName: "exclamationmark.triangle.fill")
                    .foregroundStyle(StatusRole.error.color)
            }

            if let failure = viewModel.failure {
                if let stage = failedStageName(failure.stage) {
                    Text("失敗した工程: \(stage)")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
                Text(failure.message)
                    .font(.body)
                    .textSelection(.enabled)
            }

            Text("下の「再開」ボタンで、失敗した工程から処理を再開できます。完了済みの工程はそのまま引き継がれます。")
                .font(.callout)
                .foregroundStyle(.secondary)
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 10)
                .fill(ReverbTheme.Palette.underPageBackground)
        )
        .accessibilityElement(children: .combine)
    }

    /// 終了状態の見出し（done/canceled 共通の体裁）。
    private func terminalBanner(systemImage: String, role: StatusRole, title: String, detail: String) -> some View {
        HStack(spacing: 12) {
            Image(systemName: systemImage)
                .font(.largeTitle)
                .foregroundStyle(role.color)
            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.title3.weight(.semibold))
                Text(detail)
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(title)。\(detail)")
    }

    private var connectionWarning: some View {
        Label("バックエンドと通信できていません。再接続を試みています…", systemImage: "wifi.exclamationmark")
            .font(.callout)
            .foregroundStyle(StatusRole.warning.color)
            .accessibilityElement(children: .combine)
    }

    /// ローカル完結の説明（§2「ローカル処理の説明」/ 品質優先）。
    private var localNote: some View {
        Text("すべての処理はこの Mac の中だけで行われます。品質を優先するため、完了まで時間がかかることがあります。")
            .font(.caption)
            .foregroundStyle(.secondary)
            .fixedSize(horizontal: false, vertical: true)
    }

    // MARK: - 操作

    @ViewBuilder
    private var actions: some View {
        switch viewModel.status {
        case .queued, .running:
            cancelButton
        case .done:
            Button {
                model.openCompletedJob()
            } label: {
                Label("視聴する", systemImage: "play.fill")
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .keyboardShortcut(.defaultAction)
        case .failed:
            HStack(spacing: 12) {
                resumeButton
                Button("ライブラリへ戻る") { model.returnToLibrary() }
                    .controlSize(.large)
                Button("状態を再取得") { observeNonce += 1 }
                    .controlSize(.large)
            }
        case .canceled:
            HStack(spacing: 12) {
                resumeButton
                Button("ライブラリへ戻る") { model.returnToLibrary() }
                    .controlSize(.large)
            }
        }
    }

    /// 失敗／キャンセル済みジョブを続きから再開する（`POST /jobs/{id}/resume` / USL-116）。
    /// 受理されたら再観測を貼り直し、失敗ステージ以降の再実行を完了まで追従する。
    /// 送信中は無効化して二度押しを防ぐ（`canResume` が isResuming を見る）。
    private var resumeButton: some View {
        Button {
            guard let jobId = model.activeJobId else { return }
            Task {
                if await viewModel.resume(jobId: jobId) {
                    observeNonce += 1 // 成功時のみ観測を貼り直す（失敗時は failure 表示を消さない）。
                }
            }
        } label: {
            if viewModel.isResuming {
                HStack(spacing: 8) {
                    SlowSpinner(size: 13)
                    Text("再開中…")
                }
            } else {
                Label("再開", systemImage: "arrow.clockwise")
            }
        }
        .buttonStyle(.borderedProminent)
        .controlSize(.large)
        .keyboardShortcut(.defaultAction)
        .disabled(!viewModel.canResume)
        .accessibilityHint("失敗した工程から処理を再開します")
    }

    private var cancelButton: some View {
        Button(role: .destructive) {
            showCancelConfirm = true
        } label: {
            if viewModel.isCanceling {
                HStack(spacing: 8) {
                    SlowSpinner(size: 13)
                    Text("キャンセル中…")
                }
            } else {
                Text("キャンセル")
            }
        }
        .controlSize(.large)
        .disabled(!viewModel.canCancel)
        .accessibilityHint("処理を中断してライブラリに戻れます")
    }

    // MARK: - 空状態

    private var emptyState: some View {
        VStack(spacing: 16) {
            Image(systemName: "clock.badge.questionmark")
                .font(.largeTitle)
                .foregroundStyle(.secondary)
            Text("処理中のジョブはありません")
                .font(.title3.weight(.semibold))
            Text("ライブラリから動画を選ぶと、処理の進捗がここに表示されます。")
                .font(.callout)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
            Button("ライブラリへ") { model.returnToLibrary() }
                .buttonStyle(.borderedProminent)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("処理中のジョブはありません")
    }

    // MARK: - ヘルパ

    private var clampedProgress: Double {
        min(max(viewModel.progress, 0), 1)
    }

    /// API の stage 文字列を日本語工程名に変換する（未知値はそのまま表示）。
    private func failedStageName(_ raw: String?) -> String? {
        guard let raw, !raw.isEmpty else { return nil }
        return StageName(rawValue: raw)?.displayName ?? raw
    }

    private func reflectTerminalState(_ status: JobState) {
        guard let jobId = model.activeJobId, ProcessingViewModel.isTerminal(status) else { return }
        model.updateJobState(jobId: jobId, to: status)
    }
}

/// `.task(id:)` の再起動キー。jobId 変更・再観測トリガで観測を貼り直す。
private struct ObserveKey: Equatable {
    let jobId: String?
    let nonce: Int
}
