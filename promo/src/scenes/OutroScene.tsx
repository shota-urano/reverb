import React from "react";
import {
  AbsoluteFill,
  Img,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { theme } from "../theme";

// 締め（3s）: ロゴ＋タグライン。落ち着いたミニマル。
export const OutroScene: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();

  const fade = interpolate(
    frame,
    [0, 14, durationInFrames - 10, durationInFrames],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );
  const logo = spring({ frame, fps, config: { damping: 18, mass: 0.7, stiffness: 110 } });
  const tagRise = interpolate(frame, [16, 34], [14, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const tagOpacity = interpolate(frame, [16, 30], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill
      style={{
        background: "linear-gradient(160deg, #12131a, #0a0a0d)",
        opacity: fade,
        justifyContent: "center",
        alignItems: "center",
        flexDirection: "column",
        gap: 24,
      }}
    >
      {/* ロゴ：アクセントの点 + Reverb */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 20,
          transform: `scale(${0.9 + logo * 0.1})`,
        }}
      >
        <Img
          src={staticFile("brand-icon.png")}
          style={{ width: 104, height: 104 }}
        />
        <span
          style={{
            fontFamily: "-apple-system, system-ui, sans-serif",
            color: theme.textPrimary,
            fontSize: 104,
            fontWeight: 700,
            letterSpacing: 2,
          }}
        >
          Reverb
        </span>
      </div>

      <div
        style={{
          opacity: tagOpacity,
          transform: `translateY(${tagRise}px)`,
          fontFamily: theme.fontJa,
          color: theme.textMuted,
          fontSize: 44,
          fontWeight: 600,
          letterSpacing: 2,
        }}
      >
        外国語動画を、日本語で。
      </div>
    </AbsoluteFill>
  );
};
