import { Config } from "@remotion/cli/config";

// 出力は H.264 / 1080p。X・LP・YouTube いずれにも貼れる素直な設定。
Config.setVideoImageFormat("jpeg");
Config.setOverwriteOutput(true);
