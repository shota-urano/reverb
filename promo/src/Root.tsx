import React from "react";
import { Composition } from "remotion";
import { SubtitleSwap } from "./SubtitleSwap";
import { Promo, PROMO_DURATION } from "./Promo";

// Promo = ②本編。SubtitleSwap は核カット（単体プレビュー/①オーバーレイ流用用に残す）。
export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="Promo"
        component={Promo}
        durationInFrames={PROMO_DURATION}
        fps={30}
        width={1920}
        height={1080}
      />
      <Composition
        id="SubtitleSwap"
        component={SubtitleSwap}
        durationInFrames={150}
        fps={30}
        width={1920}
        height={1080}
      />
    </>
  );
};
