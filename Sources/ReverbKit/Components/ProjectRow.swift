import SwiftUI

/// プロジェクト行の表示モデル（design-system §5.3）。
///
/// ライブラリ一覧（USL-77）が自身のデータを写して渡す。サムネイル・タイトル・任意の説明・
/// 再生時間・言語ペア・更新日・状態の要素を持つ。`…` は補助操作専用。
public struct ProjectRowData: Identifiable, Sendable, Equatable {
    public let id: String
    public let title: String
    /// 任意の短い説明（無ければ非表示）。
    public let detail: String?
    /// 再生時間（秒）。
    public let duration: Double
    /// 元言語の表示名（未判定は nil → "自動判定"）。
    public let sourceLanguage: String?
    /// 翻訳先表示名（既定 "日本語"）。
    public let targetLanguage: String
    public let updatedAt: Date
    public let state: JobState
    /// 元動画が見つからない（screens.md §1「元動画なし」）。行に警告を出す。
    public let sourceMissing: Bool
    /// 16:9 サムネイルのローカルパス（任意）。
    public let thumbnailPath: String?

    public init(
        id: String,
        title: String,
        detail: String? = nil,
        duration: Double,
        sourceLanguage: String?,
        targetLanguage: String = "日本語",
        updatedAt: Date,
        state: JobState,
        sourceMissing: Bool = false,
        thumbnailPath: String? = nil
    ) {
        self.id = id
        self.title = title
        self.detail = detail
        self.duration = duration
        self.sourceLanguage = sourceLanguage
        self.targetLanguage = targetLanguage
        self.updatedAt = updatedAt
        self.state = state
        self.sourceMissing = sourceMissing
        self.thumbnailPath = thumbnailPath
    }
}

/// プロジェクト一覧の1行（design-system §5.3）。
///
/// 行全体をクリックで開く（`onOpen`）。`…` メニューは補助操作専用で行クリックと競合させない。
public struct ProjectRow: View {
    private let data: ProjectRowData
    private let onOpen: () -> Void
    /// `…` メニュー: Finder で元動画を表示。
    private let onShowInFinder: (() -> Void)?
    /// `…` メニュー: プロジェクト情報を表示。
    private let onShowInfo: (() -> Void)?

    public init(
        data: ProjectRowData,
        onOpen: @escaping () -> Void,
        onShowInFinder: (() -> Void)? = nil,
        onShowInfo: (() -> Void)? = nil
    ) {
        self.data = data
        self.onOpen = onOpen
        self.onShowInFinder = onShowInFinder
        self.onShowInfo = onShowInfo
    }

    public var body: some View {
        HStack(spacing: 16) {
            // 行クリックで開く（キーボード/VoiceOver 対応のため Button・§7）。
            Button(action: onOpen) {
                HStack(spacing: 16) {
                    thumbnail
                    info
                    Spacer(minLength: 12)
                    StatusBadge(
                        systemImage: data.state.systemImage,
                        label: data.state.statusLabel,
                        role: data.state.role
                    )
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("\(data.title)、\(data.state.statusLabel)")
            .accessibilityHint("開く")

            optionsMenu
        }
        .padding(.vertical, 8)
        .frame(minHeight: ReverbTheme.Metrics.projectRowHeight)
    }

    private var thumbnail: some View {
        RoundedRectangle(cornerRadius: ReverbTheme.Radius.thumbnail)
            .fill(ReverbTheme.Palette.videoSurface.opacity(0.85))
            .aspectRatio(16.0 / 9.0, contentMode: .fit)
            .frame(width: 160)
            .overlay(
                Image(systemName: "film")
                    .foregroundStyle(.white.opacity(0.5))
            )
            .accessibilityHidden(true)
    }

    private var info: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(data.title)
                .font(.body.weight(.medium))
                .lineLimit(1)

            if let detail = data.detail, !detail.isEmpty {
                Text(detail)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }

            HStack(spacing: 10) {
                metaItem(systemImage: "clock", text: ReverbFormat.timecode(data.duration))
                metaItem(
                    systemImage: "character.bubble",
                    text: ReverbFormat.languagePair(source: data.sourceLanguage, target: data.targetLanguage)
                )
                metaItem(systemImage: "calendar", text: Self.dateText(data.updatedAt))
            }
            .font(.caption)
            .foregroundStyle(.secondary)

            if data.sourceMissing {
                // 色だけに依存せずアイコン＋文言で警告（§7）。
                Label("元動画が見つかりません", systemImage: "exclamationmark.triangle.fill")
                    .font(.caption)
                    .foregroundStyle(StatusRole.warning.color)
            }
        }
    }

    private func metaItem(systemImage: String, text: String) -> some View {
        HStack(spacing: 4) {
            Image(systemName: systemImage)
            Text(text)
        }
    }

    @ViewBuilder
    private var optionsMenu: some View {
        if onShowInFinder != nil || onShowInfo != nil {
            Menu {
                if let onShowInFinder {
                    Button("Finder で表示", systemImage: "folder") { onShowInFinder() }
                }
                if let onShowInfo {
                    Button("プロジェクト情報", systemImage: "info.circle") { onShowInfo() }
                }
            } label: {
                Image(systemName: "ellipsis")
                    .frame(
                        width: ReverbTheme.Metrics.primaryHitTarget,
                        height: ReverbTheme.Metrics.primaryHitTarget
                    ) // クリック対象 32×32pt（§7）
                    .contentShape(Rectangle())
            }
            .menuStyle(.borderlessButton)
            .menuIndicator(.hidden)
            .fixedSize()
            .accessibilityLabel("その他の操作")
        }
    }

    private static func dateText(_ date: Date) -> String {
        date.formatted(date: .abbreviated, time: .omitted)
    }
}
