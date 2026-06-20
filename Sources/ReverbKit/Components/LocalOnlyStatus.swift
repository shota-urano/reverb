import SwiftUI

/// 「ローカルのみで動作中」を常時示すステータス表示（design-system §5.2）。
///
/// 緑の状態点＋盾の SF Symbol＋文言。依存エンジンに問題がある場合は緑を使わず警告色にする。
/// 主要操作より強く見せない。
public struct LocalOnlyStatus: View {
    /// 依存エンジンが正常か。`nil`（未取得）・異常時は緑を使わない。
    private let healthy: Bool
    private let action: (() -> Void)?

    public init(healthy: Bool, action: (() -> Void)? = nil) {
        self.healthy = healthy
        self.action = action
    }

    public var body: some View {
        let content = HStack(spacing: 8) {
            Circle()
                .fill(healthy ? Color.green : Color.orange)
                .frame(width: 8, height: 8)
            Image(systemName: healthy ? "checkmark.shield" : "exclamationmark.shield")
                .foregroundStyle(healthy ? Color.green : Color.orange)
                .imageScale(.small)
            Text(healthy ? "ローカルのみで動作中" : "エンジンを確認してください")
                .font(.caption)
                .foregroundStyle(.secondary)
            Spacer(minLength: 0)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(healthy ? "ローカルのみで動作中" : "依存エンジンに問題があります")

        if let action {
            // 異常時はクリックで詳細を確認できる状態にする（§5.2）。
            Button(action: action) { content }
                .buttonStyle(.plain)
        } else {
            content
        }
    }
}
