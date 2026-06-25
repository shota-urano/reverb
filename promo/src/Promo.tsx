import React from "react";
import { AbsoluteFill, Audio, interpolate, Series, staticFile } from "remotion";
import { HookScene } from "./scenes/HookScene";
import { SubtitleSwap } from "./SubtitleSwap";
import { PipelineScene } from "./scenes/PipelineScene";
import { AppShowcaseScene } from "./scenes/AppShowcaseScene";
import { OutroScene } from "./scenes/OutroScene";
import { theme } from "./theme";

// ②マーケ用プロモ本編（約19.5s / 30fps）。
// つかみ → 字幕入替（核） → 仕組み6工程 → アプリ画面 → 締め。各シーンは内部で fade in/out する。
export const SCENES = {
  hook: 75, // 2.5s
  swap: 150, // 5.0s
  pipeline: 120, // 4.0s
  app: 150, // 5.0s
  outro: 90, // 3.0s
} as const;

export const PROMO_DURATION =
  SCENES.hook + SCENES.swap + SCENES.pipeline + SCENES.app + SCENES.outro;

export const Promo: React.FC = () => {
  return (
    <AbsoluteFill style={{ backgroundColor: theme.videoSurface }}>
      {/* BGM: kornevmusic「Epic」（CC0/ロイヤリティフリー）。30秒地点から開始し、
          終盤（締め）がサビのピークに重なるようにした。頭0.5s で立ち上げ、終わり1.8s で絞る。 */}
      <Audio
        src={staticFile("kornevmusic-epic-478847.mp3")}
        trimBefore={900} // 30s × 30fps
        volume={(f) =>
          interpolate(
            f,
            [0, 15, PROMO_DURATION - 54, PROMO_DURATION],
            [0, 0.7, 0.7, 0],
            { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
          )
        }
      />
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
        <Series.Sequence durationInFrames={SCENES.app}>
          <AppShowcaseScene />
        </Series.Sequence>
        <Series.Sequence durationInFrames={SCENES.outro}>
          <OutroScene />
        </Series.Sequence>
      </Series>
    </AbsoluteFill>
  );
};
