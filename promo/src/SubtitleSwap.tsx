import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { theme } from "./theme";
import { sourceCue, reverbCue } from "./data/cues";
import { VideoBackdrop } from "./components/VideoBackdrop";

// 「外国語字幕 → 日本語字幕」へパタッと入れ替わる主役カット（②の核・①のオーバーレイにも流用）。
// 構成: 元動画面（抽象） + 字幕帯 → 中盤でフリップ反転 → 日本語字幕＋JAボイスオーバー＋波形（主従）。

const SWAP_FRAME = 54; // 入れ替えトリガー（30fps想定 ≒ 1.8秒）

export const SubtitleSwap: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // フリップ進行 0→1（バネで気持ちよく）。
  const flip = spring({
    frame: frame - SWAP_FRAME,
    fps,
    config: { damping: 14, mass: 0.6, stiffness: 120 },
  });
  const swapped = frame >= SWAP_FRAME;

  // カード全体の X 回転（度）。0→90 で英語が消え、90→0(=180側) で日本語が出る感覚。
  const rotateX = interpolate(flip, [0, 0.5, 1], [0, 90, 0]);
  // 入れ替わりの境目で面が見えないように、英/日の表示を 0.5 で切替。
  const showJa = flip >= 0.5;

  return (
    <AbsoluteFill style={{ backgroundColor: theme.videoSurface }}>
      <VideoBackdrop />

      {/* 原語タグ（左上） */}
      <Tag
        style={{ left: 64, top: 56, opacity: swapped ? 0.4 : 0.9 }}
        label={showJa ? "Reverb 適用" : "原語: EN"}
        accent={showJa}
      />

      {/* JA ボイスオーバー バッジ + 波形（右上・入替後にフェードイン） */}
      <VoiceOverBadge progress={showJa ? flip : 0} frame={frame} />

      {/* 字幕帯（下） */}
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: 96,
          display: "flex",
          justifyContent: "center",
          perspective: 1200,
        }}
      >
        <div
          style={{
            transform: `rotateX(${rotateX}deg)`,
            transformStyle: "preserve-3d",
            background: theme.subtitleScrim,
            borderRadius: theme.radiusPlayer,
            padding: "26px 44px",
            maxWidth: 1320,
          }}
        >
          <SubtitleText
            lines={showJa ? reverbCue.lines : sourceCue.lines}
            ja={showJa}
          />
          {/* 入替後にアクセント下線がスッと伸びる */}
          <div
            style={{
              height: 4,
              marginTop: 18,
              borderRadius: 2,
              background: theme.accent,
              width: `${interpolate(showJa ? flip : 0, [0.5, 1], [0, 100], {
                extrapolateLeft: "clamp",
                extrapolateRight: "clamp",
              })}%`,
            }}
          />
        </div>
      </div>
    </AbsoluteFill>
  );
};

const SubtitleText: React.FC<{ lines: string[]; ja: boolean }> = ({
  lines,
  ja,
}) => (
  <div
    style={{
      fontFamily: ja ? theme.fontJa : "-apple-system, system-ui, sans-serif",
      color: theme.textPrimary,
      fontSize: ja ? 58 : 52,
      fontWeight: 600,
      lineHeight: 1.32,
      textAlign: "center",
      letterSpacing: ja ? 0.5 : 0,
    }}
  >
    {lines.map((line, i) => (
      <div key={i}>{line}</div>
    ))}
  </div>
);

const Tag: React.FC<{
  style: React.CSSProperties;
  label: string;
  accent: boolean;
}> = ({ style, label, accent }) => (
  <div
    style={{
      position: "absolute",
      padding: "8px 16px",
      borderRadius: theme.radiusBadge,
      fontFamily: theme.fontJa,
      fontSize: 24,
      fontWeight: 600,
      color: theme.textPrimary,
      background: accent ? theme.accent : "rgba(255,255,255,0.12)",
      border: "1px solid rgba(255,255,255,0.16)",
      ...style,
    }}
  >
    {label}
  </div>
);

// JA ボイスオーバー：日本語主（大）/ 元音声従（小）を波形の大小で表現。
const VoiceOverBadge: React.FC<{ progress: number; frame: number }> = ({
  progress,
  frame,
}) => {
  if (progress <= 0) return null;
  const opacity = interpolate(progress, [0, 1], [0, 1]);
  const slide = interpolate(progress, [0, 1], [24, 0]);
  return (
    <div
      style={{
        position: "absolute",
        right: 64,
        top: 56,
        opacity,
        transform: `translateY(${slide}px)`,
        display: "flex",
        flexDirection: "column",
        alignItems: "flex-end",
        gap: 12,
      }}
    >
      <div
        style={{
          padding: "8px 16px",
          borderRadius: theme.radiusBadge,
          background: theme.accent,
          color: theme.textPrimary,
          fontFamily: theme.fontJa,
          fontSize: 24,
          fontWeight: 700,
        }}
      >
        JA ボイスオーバー
      </div>
      <Waveform frame={frame} gain={1} label="日本語 100%" />
      <Waveform frame={frame} gain={0.18} label="元音声 8%" muted />
    </div>
  );
};

const BARS = 26;
const Waveform: React.FC<{
  frame: number;
  gain: number;
  label: string;
  muted?: boolean;
}> = ({ frame, gain, label, muted }) => (
  <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
    <span
      style={{
        fontFamily: theme.fontJa,
        fontSize: 18,
        color: muted ? theme.textMuted : theme.textPrimary,
        width: 110,
        textAlign: "right",
      }}
    >
      {label}
    </span>
    <div style={{ display: "flex", alignItems: "center", gap: 4, height: 40 }}>
      {Array.from({ length: BARS }).map((_, i) => {
        // 決定論的な波形（frame で脈動）。Math.random は使わない。
        const base = Math.abs(Math.sin(i * 0.7 + 1.3) * 0.6 + 0.4);
        const pulse = 0.5 + 0.5 * Math.sin(frame / 4 + i * 0.9);
        const h = 6 + base * pulse * 34 * gain;
        return (
          <div
            key={i}
            style={{
              width: 4,
              height: h,
              borderRadius: 2,
              background: muted ? theme.textMuted : theme.accent,
            }}
          />
        );
      })}
    </div>
  </div>
);
