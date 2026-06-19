import Foundation

/// サイドバーの主ナビゲーション項目（screens.md 共通ナビ / design-system §5.1）。
public enum SidebarSection: String, CaseIterable, Identifiable, Sendable {
    case library
    case processing
    case settings

    public var id: String { rawValue }

    /// サイドバー表示名。
    public var title: String {
        switch self {
        case .library: return "ライブラリ"
        case .processing: return "処理中"
        case .settings: return "設定"
        }
    }

    /// SF Symbol（design-system §6・独自描画は使わない）。
    public var systemImage: String {
        switch self {
        case .library: return "folder"
        case .processing: return "clock.arrow.circlepath"
        case .settings: return "gearshape"
        }
    }
}
