import React from "react";
import {
  AbsoluteFill,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { theme } from "../theme";
import { sourceCue } from "../data/cues";
import { VideoBackdrop } from "../components/VideoBackdrop";

// つかみ（0–2.5s）: 外国語動画が流れ、英語字幕＋「分からない」コピーで課題提示。
export const HookScene: React.FC = () => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();

  const fade = interpolate(
    frame,
    [0, 12, durationInFrames - 12, durationInFrames],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );
  const copyRise = interpolate(frame, [6, 24], [18, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill style={{ backgroundColor: theme.videoSurface, opacity: fade }}>
      <VideoBackdrop />

      {/* 課題コピー（中央上） */}
      <AbsoluteFill
        style={{
          justifyContent: "center",
          alignItems: "center",
          paddingBottom: 220,
        }}
      >
        <div
          style={{
            transform: `translateY(${copyRise}px)`,
            fontFamily: theme.fontJa,
            color: theme.textPrimary,
            fontSize: 72,
            fontWeight: 700,
            letterSpacing: 1,
            textShadow: "0 4px 24px rgba(0,0,0,0.6)",
          }}
        >
          この動画、何て言ってる？
        </div>
      </AbsoluteFill>

      {/* 元動画の英語字幕（下・帯付き） */}
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: 96,
          display: "flex",
          justifyContent: "center",
        }}
      >
        <div
          style={{
            background: theme.subtitleScrim,
            borderRadius: theme.radiusPlayer,
            padding: "22px 40px",
            fontFamily: "-apple-system, system-ui, sans-serif",
            color: theme.textPrimary,
            fontSize: 50,
            fontWeight: 600,
            lineHeight: 1.32,
            textAlign: "center",
            maxWidth: 1280,
          }}
        >
          {sourceCue.lines.map((line, i) => (
            <div key={i}>{line}</div>
          ))}
        </div>
      </div>
    </AbsoluteFill>
  );
};
