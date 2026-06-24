import SwiftUI

/// 工程順の正規化（テスト対象・UI 非依存）。
///
/// `JobStatus.stages` が部分集合でも、6工程を **固定順**（extract→…→mix）で欠けなく並べる。
/// UI 側で順序や重みを再計算しない方針なので、状態値そのものはバックエンドのものを使う。
public enum StageOrder {
    /// 与えられた進捗を固定順に整列し、未提供の工程は `pending` で補完する。
    public static func normalized(_ stages: [StageProgress]) -> [StageProgress] {
        var byName: [StageName: StageProgress] = [:]
        for stage in stages where byName[stage.name] == nil {
            byName[stage.name] = stage
        }
        return StageName.allCases.map { name in
            byName[name] ?? StageProgress(name: name, status: .pending, progress: 0)
        }
    }
}

/// 6工程の状態一覧（design-system §5.4 / screens.md §2）。
///
/// 工程名は API の固定順を日本語表示し、done/running/pending/failed/canceled を
/// アイコン＋ラベルで表す（色だけに依存しない・§7）。
public struct StageProgressList: View {
    private let stages: [StageProgress]
    /// 失敗工程の「エラーメッセージへの導線」（§5.4）。指定時のみ failed 行にボタンを出す。
    private let onSelectFailed: ((StageName) -> Void)?

    public init(stages: [StageProgress], onSelectFailed: ((StageName) -> Void)? = nil) {
        self.stages = StageOrder.normalized(stages)
        self.onSelectFailed = onSelectFailed
    }

    public var body: some View {
        VStack(spacing: 8) {
            ForEach(stages) { stage in
                StageProgressRow(stage: stage, onSelectFailed: onSelectFailed)
                if stage.id != StageName.mix {
                    Divider() // 影でなく区切り線で整理（§4）
                }
            }
        }
    }
}

/// 工程1行。
struct StageProgressRow: View {
    let stage: StageProgress
    let onSelectFailed: ((StageName) -> Void)?

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    /// 工程の状態アイコン。running 中は循環矢印をゆっくり回して進行を示す
    /// （表示リフレッシュ同期で確実に回す）。Reduce Motion 時は静止（§7）。
    @ViewBuilder private var stageIcon: some View {
        let icon = Image(systemName: stage.status.systemImage)
            .foregroundStyle(stage.status.role.color)
            .imageScale(.large)
            .frame(width: 24)
        if stage.status == .running && !reduceMotion {
            TimelineView(.animation) { context in
                let t = context.date.timeIntervalSinceReferenceDate
                let period = 2.6 // 1回転の秒数（大きいほどゆっくり）
                let angle = (t.truncatingRemainder(dividingBy: period) / period) * 360.0
                icon.rotationEffect(.degrees(angle))
            }
        } else {
            icon
        }
    }

    var body: some View {
        HStack(spacing: 12) {
            stageIcon

            VStack(alignment: .leading, spacing: 4) {
                Text(stage.name.displayName)
                    .font(.body.weight(.medium))

                if stage.status == .running {
                    // running はアクセント背景の部分進捗バー＋進捗率（§5.4）。
                    ProgressView(value: clampedProgress)
                        .progressViewStyle(.linear)
                        .tint(ReverbTheme.Palette.accent)
                        .animation(reduceMotion ? nil : .default, value: clampedProgress) // Reduce Motion で抑制（§7）
                } else {
                    Text(stage.status.statusLabel)
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
            }

            Spacer(minLength: 8)

            trailing
        }
        .padding(.vertical, 4)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(accessibilityLabel)
    }

    @ViewBuilder
    private var trailing: some View {
        switch stage.status {
        case .running:
            Text(ReverbFormat.percent(clampedProgress))
                .font(.callout.monospacedDigit())
                .foregroundStyle(.secondary)
        case .failed:
            if let onSelectFailed {
                Button("詳細") { onSelectFailed(stage.name) }
                    .buttonStyle(.link)
            }
        default:
            EmptyView()
        }
    }

    private var clampedProgress: Double {
        min(max(stage.progress, 0), 1)
    }

    private var accessibilityLabel: String {
        if stage.status == .running {
            return "\(stage.name.displayName) \(stage.status.statusLabel) \(ReverbFormat.percent(clampedProgress))"
        }
        return "\(stage.name.displayName) \(stage.status.statusLabel)"
    }
}
