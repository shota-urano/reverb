import Foundation

/// 既定 `JobSettings`（次回以降の `POST /jobs` に渡す設定）のローカル保存境界
/// （screens.md §4「保存」/ 08 §6）。
///
/// 保存先はローカルのみ（クラウド送信なし・ルール1）。テスト時はモックに差し替える（ルール3）。
public protocol SettingsStore: Sendable {
    /// 保存済みの既定設定。未保存なら nil（このときバックエンド既定が使われる）。
    func load() -> JobSettings?
    /// 既定設定を保存する。
    func save(_ settings: JobSettings)
    /// 保存済み設定を消す（保存値を捨ててバックエンド既定に委ねる）。
    func clear()
}

/// `UserDefaults` を用いる既定実装。1キーに JSON で格納する（ローカル完結）。
public struct UserDefaultsSettingsStore: SettingsStore {
    // UserDefaults はスレッドセーフだが Sendable 準拠ではないため unsafe で明示する。
    private nonisolated(unsafe) let defaults: UserDefaults
    private let key: String

    public init(defaults: UserDefaults = .standard, key: String = "reverb.jobSettings.default") {
        self.defaults = defaults
        self.key = key
    }

    public func load() -> JobSettings? {
        guard let data = defaults.data(forKey: key) else { return nil }
        // 旧バージョンの形式変更で壊れた値は黙って無視し、バックエンド既定に委ねる。
        return try? JSONDecoder().decode(JobSettings.self, from: data)
    }

    public func save(_ settings: JobSettings) {
        guard let data = try? JSONEncoder().encode(settings) else { return }
        defaults.set(data, forKey: key)
    }

    public func clear() {
        defaults.removeObject(forKey: key)
    }
}
