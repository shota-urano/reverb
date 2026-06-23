import SwiftUI

/// デザイントークン（design-system §2 色 / §3 タイポ / §4 形状 / §1 レイアウト）。
///
/// マジックナンバーを各 View に散らさず一元化する。色はセマンティックカラーを優先し、
/// アクセントのみ Indigo 基準色 `#4F63E9` を定義する（選択/進捗/主要ボタン/スライダーに限定・§2）。
/// 広い背景面にアクセント色を使わない。
public enum ReverbTheme {

    // MARK: - 色（§2）

    public enum Palette {
        /// アクセント Indigo 基準 `#4F63E9`。広い背景面には使わない（§2）。
        public static let accent = Color(red: 79.0 / 255.0, green: 99.0 / 255.0, blue: 233.0 / 255.0)
        /// メイン背景。
        public static let windowBackground = Color(nsColor: .windowBackgroundColor)
        /// 区切り線（リスト/フォームは影でなくこれで整理・§4）。
        public static let separator = Color(nsColor: .separatorColor)
        /// 補助面（プレースホルダ等）。
        public static let underPageBackground = Color(nsColor: .underPageBackgroundColor)
        /// 動画面（黒〜チャコール・§2）。
        public static let videoSurface = Color.black
        /// 字幕背景帯（黒 68〜76%・§2）。
        public static let subtitleScrim = Color.black.opacity(0.72)
        /// 選択背景（アクセント 8〜12%・§2）。
        public static let selection = accent.opacity(0.10)
    }

    // MARK: - 動画面（§5 / USL-89）

    public enum Player {
        /// 動画面のアスペクト比 16:9。マジックナンバーにせずここで一元管理する（USL-89）。
        public static let videoAspectRatio: CGFloat = 16.0 / 9.0
    }

    // MARK: - 形状（§4）

    public enum Radius {
        /// 動画プレーヤー角丸 12〜14pt。
        public static let player: CGFloat = 13
        /// ボタン角丸 8〜10pt。
        public static let button: CGFloat = 9
        /// サムネイル角丸 8pt。
        public static let thumbnail: CGFloat = 8
        /// 選択行角丸 8〜10pt。
        public static let selectedRow: CGFloat = 9
    }

    // MARK: - 寸法（§1 レイアウト / §7 アクセシビリティ）

    public enum Metrics {
        /// コンテンツ外周余白。
        public static let contentPadding: CGFloat = 32
        /// セクション間隔 28〜32pt。
        public static let sectionSpacing: CGFloat = 28
        /// 同一セクション内の要素間隔 12〜16pt。
        public static let elementSpacing: CGFloat = 14
        /// フォームコントロール高さ 30〜34pt。
        public static let formControlHeight: CGFloat = 32
        /// 通常行高。
        public static let rowHeight: CGFloat = 52
        /// プロジェクト行高 112〜136pt。
        public static let projectRowHeight: CGFloat = 120
        /// クリック対象の最低サイズ 28×28pt（§7）。
        public static let minHitTarget: CGFloat = 28
        /// 主要操作のクリック対象 32×32pt 以上（§7）。
        public static let primaryHitTarget: CGFloat = 32
    }
}
