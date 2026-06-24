import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";

// 抽象的な「講義動画」背景（ゆっくり漂うグラデ＋周辺減光）。全シーン共通。
export const VideoBackdrop: React.FC = () => {
  const frame = useCurrentFrame();
  const drift = Math.sin(frame / 40) * 60;
  const drift2 = Math.cos(frame / 55) * 80;
  return (
    <AbsoluteFill>
      <AbsoluteFill
        style={{
          background: `radial-gradient(60% 60% at ${30 + drift / 10}% ${
            35 + drift2 / 12
          }%, rgba(79,99,233,0.45), transparent 70%),
            radial-gradient(50% 50% at ${72 - drift / 14}% ${
            68 - drift2 / 14
          }%, rgba(255,140,90,0.22), transparent 70%),
            linear-gradient(160deg, #14151b, #0b0b0e)`,
        }}
      />
      <AbsoluteFill
        style={{ boxShadow: "inset 0 0 240px 80px rgba(0,0,0,0.6)" }}
      />
    </AbsoluteFill>
  );
};
