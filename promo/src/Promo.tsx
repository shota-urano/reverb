import React from "react";
import { AbsoluteFill, Series } from "remotion";
import { HookScene } from "./scenes/HookScene";
import { SubtitleSwap } from "./SubtitleSwap";
import { PipelineScene } from "./scenes/PipelineScene";
import { OutroScene } from "./scenes/OutroScene";
import { theme } from "./theme";

// ②マーケ用プロモ本編（約14.5s / 30fps）。
// つかみ → 字幕入替（核） → 仕組み6工程 → 締め。各シーンは内部で fade in/out する。
export const SCENES = {
  hook: 75, // 2.5s
  swap: 150, // 5.0s
  pipeline: 120, // 4.0s
  outro: 90, // 3.0s
} as const;

export const PROMO_DURATION =
  SCENES.hook + SCENES.swap + SCENES.pipeline + SCENES.outro;

export const Promo: React.FC = () => {
  return (
    <AbsoluteFill style={{ backgroundColor: theme.videoSurface }}>
      <Series>
        <Series.Sequence durationInFrames={SCENES.hook}>
          <HookScene />
        </Series.Sequence>
        <Series.Sequence durationInFrames={SCENES.swap}>
          <SubtitleSwap />
        </Series.Sequence>
        <Series.Sequence durationInFrames={SCENES.pipeline}>
          <PipelineScene />
        </Series.Sequence>
        <Series.Sequence durationInFrames={SCENES.outro}>
          <OutroScene />
        </Series.Sequence>
      </Series>
    </AbsoluteFill>
  );
};
