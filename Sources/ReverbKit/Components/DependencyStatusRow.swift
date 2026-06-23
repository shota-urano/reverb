import SwiftUI

/// 依存エンジン一覧の組み立て（テスト対象・UI 非依存）。
public enum DependencyCatalog {
    /// 表示名と可用性の組を固定順で返す。エンジン名は設定値ではなく固定の表示名（ルール1の構成エンジン）。
    public static func items(from status: DependencyStatus) -> [(name: String, available: Bool)] {
        [
            (name: "ffmpeg", available: status.ffmpeg),
            (name: "mlx-whisper", available: status.mlxWhisper),
            (name: "Ollama", available: status.ollama),
            (name: "TTS", available: status.tts),
        ]
    }
}

/// 依存エンジンの状態1行（design-system §5 / screens.md §4「依存エンジン」）。
///
/// 状態点＋アイコン＋ラベルで「接続済み / 未接続」を表す（色だけに依存しない・§7）。
/// 外部サービスへの誘導は行わない（ルール1）。
public struct DependencyStatusRow: View {
    private let name: String
    private let available: Bool
    /// 未接続時の説明（任意）。起動や確認が必要であることを伝える（screens §4）。
    private let detail: String?

    public init(name: String, available: Bool, detail: String? = nil) {
        self.name = name
        self.available = available
        self.detail = detail
    }

    public var body: some View {
        HStack(spacing: 10) {
            Circle()
                .fill(role.color)
                .frame(width: 8, height: 8)
                .accessibilityHidden(true)

            Image(systemName: available ? "checkmark.circle.fill" : "xmark.circle")
                .foregroundStyle(role.color)
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: 2) {
                Text(name)
                    .font(.body)
                if let detail, !detail.isEmpty, !available {
                    Text(detail)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            Spacer(minLength: 8)

            Text(statusLabel)
                .font(.callout)
                .foregroundStyle(role.color)
        }
        .padding(.vertical, 4)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(name) \(statusLabel)")
    }

    private var statusLabel: String { available ? "接続済み" : "未接続" }
    private var role: StatusRole { available ? .success : .warning }
}

/// 依存エンジン4種をまとめて表示する（screens.md §4 / design-system §5）。
public struct DependencyStatusList: View {
    private let dependencies: DependencyStatus

    public init(dependencies: DependencyStatus) {
        self.dependencies = dependencies
    }

    public var body: some View {
        VStack(spacing: 0) {
            let items = DependencyCatalog.items(from: dependencies)
            ForEach(Array(items.enumerated()), id: \.element.name) { index, item in
                DependencyStatusRow(name: item.name, available: item.available)
                if index < items.count - 1 {
                    Divider() // 影でなく区切り線（§4）
                }
            }
        }
    }
}
