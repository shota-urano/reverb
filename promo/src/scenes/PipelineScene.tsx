import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { theme } from "../theme";
import { VideoBackdrop } from "../components/VideoBackdrop";

// 仕組み（4s）: 6工程チップが順に点灯 →「全部、あなたのMacの中だけで。」でローカル完結を強調。
// 工程名は Swift StageName.displayName と一致（音声抽出→…→ミックス）。
const STAGES = [
  "音声抽出",
  "文字起こし",
  "翻訳",
  "字幕整形",
  "音声合成",
  "ミックス",
];

export const PipelineScene: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();

  const fade = interpolate(
    frame,
    [0, 12, durationInFrames - 12, durationInFrames],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  // 各チップの点灯開始フレーム（順送り）。
  const stepStart = 10;
  const stepGap = 9;

  // ローカル完結コピーは工程点灯後に出す。
  const localStart = stepStart + STAGES.length * stepGap + 6;
  const localProgress = spring({
    frame: frame - localStart,
    fps,
    config: { damping: 16, mass: 0.6, stiffness: 120 },
  });

  return (
    <AbsoluteFill style={{ backgroundColor: theme.videoSurface, opacity: fade }}>
      <VideoBackdrop />

      <AbsoluteFill
        style={{
          justifyContent: "center",
          alignItems: "center",
          flexDirection: "column",
          gap: 56,
        }}
      >
        {/* 工程チップ列 */}
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          {STAGES.map((name, i) => {
            const start = stepStart + i * stepGap;
            const lit = spring({
              frame: frame - start,
              fps,
              config: { damping: 18, mass: 0.5, stiffness: 140 },
            });
            return (
              <React.Fragment key={name}>
                <Chip name={name} lit={lit} />
                {i < STAGES.length - 1 && <Arrow lit={lit} />}
              </React.Fragment>
            );
          })}
        </div>

        {/* ローカル完結コピー */}
        <div
          style={{
            opacity: localProgress,
            transform: `translateY(${interpolate(
              localProgress,
              [0, 1],
              [16, 0]
            )}px)`,
            display: "flex",
            alignItems: "center",
            gap: 18,
          }}
        >
          <CloudOff />
          <span
            style={{
              fontFamily: theme.fontJa,
              color: theme.textPrimary,
              fontSize: 60,
              fontWeight: 700,
              letterSpacing: 1,
            }}
          >
            全部、あなたの Mac の中だけで。
          </span>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const Chip: React.FC<{ name: string; lit: number }> = ({ name, lit }) => (
  <div
    style={{
      padding: "16px 22px",
      borderRadius: 12,
      fontFamily: theme.fontJa,
      fontSize: 30,
      fontWeight: 600,
      whiteSpace: "nowrap",
      color: theme.textPrimary,
      background: `rgba(79,99,233,${0.16 + lit * 0.74})`,
      border: `1px solid rgba(255,255,255,${0.14 + lit * 0.3})`,
      transform: `scale(${0.92 + lit * 0.08})`,
      boxShadow: lit > 0.5 ? "0 8px 30px rgba(79,99,233,0.4)" : "none",
    }}
  >
    {name}
  </div>
);

const Arrow: React.FC<{ lit: number }> = ({ lit }) => (
  <div
    style={{
      fontSize: 28,
      color: theme.textPrimary,
      opacity: 0.3 + lit * 0.7,
    }}
  >
    →
  </div>
);

// クラウド送信しない＝雲に斜線（簡易アイコン）。
const CloudOff: React.FC = () => (
  <svg width={56} height={56} viewBox="0 0 24 24" fill="none">
    <path
      d="M7 18h10a4 4 0 0 0 .5-7.97A6 6 0 0 0 6 9a4.5 4.5 0 0 0 1 8.9"
      stroke={theme.accent}
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path
      d="M3 3l18 18"
      stroke="#FF7A6B"
      strokeWidth={2}
      strokeLinecap="round"
    />
  </svg>
);
