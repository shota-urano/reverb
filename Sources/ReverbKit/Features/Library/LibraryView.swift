import SwiftUI
import AppKit
import UniformTypeIdentifiers

/// ライブラリ画面（screens.md §1 / 08 §3）。
///
/// ローカル動画（MP4）を選択またはドロップして処理を開始し、既存プロジェクトを再度開く。
/// 状態取得・ジョブ作成は ViewModel/AppModel 経由で行い、View は描画と操作通知に徹する（ルール3）。
public struct LibraryView: View {
    /// 遷移ハブ兼プロジェクト台帳（一覧・ナビゲーションの単一情報源）。
    private let model: AppModel
    @State private var viewModel: LibraryViewModel
    @State private var isDropTargeted = false
    /// 「…」→ プロジェクト情報シートの対象。
    @State private var infoProject: ProjectRowData?

    public init(model: AppModel) {
        self.model = model
        _viewModel = State(wrappedValue: LibraryViewModel(jobRepository: model.jobRepository))
    }

    public var body: some View {
        ScreenScaffold(title: "ライブラリ") {
            Text("外国語の動画を、日本語の吹き替えと字幕で視聴できます。")
                .font(.body)
                .foregroundStyle(.secondary)

            if model.projects.isEmpty {
                emptyState
            } else {
                populatedState
            }
        }
        .overlay { if viewModel.isCreating { creatingOverlay } }
        .alert(
            "処理を開始できません",
            isPresented: Binding(
                get: { viewModel.errorMessage != nil },
                set: { if !$0 { viewModel.dismissError() } }
            )
        ) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(viewModel.errorMessage ?? "")
        }
        .sheet(item: $infoProject) { ProjectInfoSheet(data: $0) }
    }

    // MARK: - 状態別レイアウト

    /// 空: ドロップ領域を中央寄りにし、最初の動画選択を促す（screens.md §1）。
    private var emptyState: some View {
        VStack(spacing: 20) {
            selectButton
            DropZone(isTargeted: isDropTargeted, compact: false)
                .dropDestination(for: URL.self) { urls, _ in accept(urls) } isTargeted: { isDropTargeted = $0 }
            Text("MP4に対応")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: 560)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
    }

    /// 一覧あり: 上部に選択・ドロップ、その下にプロジェクト一覧。
    private var populatedState: some View {
        VStack(alignment: .leading, spacing: ReverbTheme.Metrics.elementSpacing) {
            HStack(alignment: .firstTextBaseline) {
                selectButton
                Spacer()
                Text("MP4に対応")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            DropZone(isTargeted: isDropTargeted, compact: true)
                .dropDestination(for: URL.self) { urls, _ in accept(urls) } isTargeted: { isDropTargeted = $0 }

            projectList
        }
    }

    private var projectList: some View {
        ScrollView {
            LazyVStack(spacing: 0) {
                ForEach(model.projects) { project in
                    ProjectRow(
                        data: project,
                        onOpen: { model.open(project) },
                        onShowInFinder: model.sourcePath(for: project.id) == nil
                            ? nil
                            : { revealInFinder(project) },
                        onShowInfo: { infoProject = project }
                    )
                    Divider()
                }
            }
        }
        .accessibilityLabel("プロジェクト一覧")
    }

    private var selectButton: some View {
        Button {
            presentOpenPanel()
        } label: {
            Label("動画を選択", systemImage: "plus")
        }
        .buttonStyle(.borderedProminent)
        .controlSize(.large)
        .disabled(viewModel.isCreating)
        .keyboardShortcut("o", modifiers: .command)
        .accessibilityHint("MP4 動画を選んで処理を開始します")
    }

    private var creatingOverlay: some View {
        ZStack {
            Color(nsColor: .windowBackgroundColor).opacity(0.6)
            VStack(spacing: 12) {
                ProgressView()
                Text("処理を準備しています…")
                    .font(.body)
                    .foregroundStyle(.secondary)
            }
        }
        .ignoresSafeArea()
        .accessibilityElement(children: .combine)
        .accessibilityLabel("処理を準備しています")
    }

    // MARK: - 操作

    /// ドロップされた URL を受け付ける（最初の1件のみ・MVP は単一選択）。
    private func accept(_ urls: [URL]) -> Bool {
        guard let url = urls.first else { return false }
        handle(url)
        return true
    }

    private func handle(_ url: URL) {
        Task {
            if let response = await viewModel.submit(videoURL: url) {
                model.didCreateJob(
                    response,
                    title: LibraryViewModel.projectTitle(from: url),
                    sourcePath: url.path
                )
            }
        }
    }

    /// `NSOpenPanel` で MP4 を選ぶ（screens.md §1）。
    private func presentOpenPanel() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.mpeg4Movie]
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        panel.canChooseFiles = true
        panel.message = "処理する動画（MP4）を選択してください"
        panel.prompt = "選択"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        handle(url)
    }

    private func revealInFinder(_ project: ProjectRowData) {
        guard let path = model.sourcePath(for: project.id) else { return }
        NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: path)])
    }
}

// MARK: - ドロップ領域

/// 動画ドロップ領域（破線枠・SF Symbol / design-system §4,§6）。
private struct DropZone: View {
    let isTargeted: Bool
    /// 一覧があるときは高さを抑える。
    let compact: Bool

    var body: some View {
        VStack(spacing: 10) {
            Image(systemName: "arrow.down.doc")
                .font(compact ? .title2 : .largeTitle)
                .foregroundStyle(isTargeted ? StatusRole.accent.color : .secondary)
            Text("動画ファイルをここにドロップ")
                .font(.body)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
        .frame(minHeight: compact ? 96 : 220)
        .background(
            RoundedRectangle(cornerRadius: ReverbTheme.Radius.player)
                .fill(isTargeted ? ReverbTheme.Palette.selection : ReverbTheme.Palette.underPageBackground)
        )
        .overlay(
            RoundedRectangle(cornerRadius: ReverbTheme.Radius.player)
                .strokeBorder(
                    isTargeted ? ReverbTheme.Palette.accent : ReverbTheme.Palette.separator,
                    style: StrokeStyle(lineWidth: 1.5, dash: [6])
                )
        )
        .accessibilityElement(children: .combine)
        .accessibilityLabel("動画ファイルをここにドロップ。MP4に対応")
    }
}

// MARK: - プロジェクト情報シート

/// 「…」→ プロジェクト情報（screens.md §1）。成果物の手動編集・書き出しは置かない（スコープ外）。
private struct ProjectInfoSheet: View {
    let data: ProjectRowData
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(data.title)
                .font(.title3.weight(.semibold))
                .accessibilityAddTraits(.isHeader)

            Grid(alignment: .leadingFirstTextBaseline, horizontalSpacing: 16, verticalSpacing: 8) {
                infoRow("状態", data.state.statusLabel)
                infoRow("再生時間", ReverbFormat.timecode(data.duration))
                infoRow("言語", ReverbFormat.languagePair(source: data.sourceLanguage, target: data.targetLanguage))
                infoRow("更新", data.updatedAt.formatted(date: .abbreviated, time: .shortened))
            }
            .font(.callout)

            HStack {
                Spacer()
                Button("閉じる") { dismiss() }
                    .keyboardShortcut(.defaultAction)
            }
        }
        .padding(24)
        .frame(minWidth: 360)
    }

    private func infoRow(_ label: String, _ value: String) -> some View {
        GridRow {
            Text(label)
                .foregroundStyle(.secondary)
                .gridColumnAlignment(.leading)
            Text(value)
        }
    }
}
