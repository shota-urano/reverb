import React from "react";
import {
  AbsoluteFill,
  interpolate,
  OffthreadVideo,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { theme } from "../theme";

// アプリ画面ショーケース（5s）: 実アプリ（Reverb）の Player を画面収録した本物の映像。
// public/app-player.mp4 = 完成プロジェクトの再生中（日本語字幕＋吹き替え・音量バランス）を
// screencapture で録ったもの。モックではなく実機キャプチャ。
export const AppShowcaseScene: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();

  const fade = interpolate(
    frame,
    [0, 14, durationInFrames - 12, durationInFrames],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  // ウィンドウが軽く奥から立ち上がる。
  const enter = spring({ frame, fps, config: { damping: 18, mass: 0.8, stiffness: 90 } });
  const scale = interpolate(enter, [0, 1], [0.94, 1]) * 1.18;
  const rise = interpolate(enter, [0, 1], [40, 0]);

  return (
    <AbsoluteFill
      style={{
        background: "radial-gradient(70% 70% at 50% 40%, #1a1b22, #0a0a0d)",
        opacity: fade,
        justifyContent: "center",
        alignItems: "center",
      }}
    >
      <div
        style={{
          transform: `translateY(${rise}px) scale(${scale})`,
          borderRadius: 16,
          overflow: "hidden",
          boxShadow: "0 40px 120px rgba(0,0,0,0.6), 0 0 0 1px rgba(255,255,255,0.08)",
          lineHeight: 0,
        }}
      >
        <OffthreadVideo
          src={staticFile("app-player.mp4")}
          muted
          style={{ width: 1500, height: "auto", display: "block" }}
        />
      </div>
    </AbsoluteFill>
  );
};
