import SwiftUI

/// 状態の意味的役割。**色だけで状態を表さない**ため、ラベル・SF Symbol と組で使う（§7）。
public enum StatusRole: Sendable {
    case neutral
    case accent
    case success
    case warning
    case error

    public var color: Color {
        switch self {
        case .neutral: return Color.secondary
        case .accent: return ReverbTheme.Palette.accent
        case .success: return Color.green
        case .warning: return Color.orange
        case .error: return Color.red
        }
    }
}

// MARK: - 工程状態の表示（design-system §5.4）

public extension StageState {
    /// 日本語の状態ラベル。
    var statusLabel: String {
        switch self {
        case .pending: return "待機中"
        case .running: return "実行中"
        case .done: return "完了"
        case .failed: return "失敗"
        case .canceled: return "キャンセル済み"
        }
    }

    /// 状態を表す SF Symbol（独自描画を使わない・§6）。
    var systemImage: String {
        switch self {
        case .pending: return "circle"
        case .running: return "arrow.triangle.2.circlepath"
        case .done: return "checkmark.circle.fill"
        case .failed: return "exclamationmark.circle.fill"
        case .canceled: return "minus.circle"
        }
    }

    /// 意味的役割。done は「青いチェック」、running はアクセント、pending/canceled は中立、failed はエラー（§5.4）。
    var role: StatusRole {
        switch self {
        case .pending: return .neutral
        case .running: return .accent
        case .done: return .accent
        case .failed: return .error
        case .canceled: return .neutral
        }
    }
}

// MARK: - ジョブ状態の表示（screens.md §2 / プロジェクト行）

public extension JobState {
    /// プロジェクト行・処理画面で使う日本語ラベル。
    var statusLabel: String {
        switch self {
        case .queued: return "準備中"
        case .running: return "処理中"
        case .done: return "視聴できます"
        case .failed: return "失敗"
        case .canceled: return "キャンセル済み"
        }
    }

    var systemImage: String {
        switch self {
        case .queued: return "clock"
        case .running: return "clock.arrow.circlepath"
        case .done: return "checkmark.circle.fill"
        case .failed: return "exclamationmark.triangle.fill"
        case .canceled: return "minus.circle"
        }
    }

    var role: StatusRole {
        switch self {
        case .queued: return .neutral
        case .running: return .accent
        case .done: return .success
        case .failed: return .error
        case .canceled: return .neutral
        }
    }
}

/// アイコン＋ラベルで状態を示す小バッジ（色だけに依存しない・§7）。
public struct StatusBadge: View {
    private let systemImage: String
    private let label: String
    private let role: StatusRole

    public init(systemImage: String, label: String, role: StatusRole) {
        self.systemImage = systemImage
        self.label = label
        self.role = role
    }

    public var body: some View {
        HStack(spacing: 4) {
            Image(systemName: systemImage)
                .imageScale(.small)
            Text(label)
                .font(.callout)
        }
        .foregroundStyle(role.color)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(label)
    }
}
