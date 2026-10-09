import type { DeviceState } from "./types";

const labels: Record<DeviceState, { zh: string; en: string }> = {
  offline: { zh: "离线", en: "Offline" },
  discovered: { zh: "已发现 · 未连接", en: "Discovered · Disconnected" },
  connecting: { zh: "连接中", en: "Connecting" },
  idle: { zh: "已连接 · 空闲", en: "Connected · Idle" },
  busy: { zh: "忙碌", en: "Busy" },
  needs_recovery: { zh: "需恢复", en: "Needs recovery" },
};

export function deviceStateLabel(state: DeviceState, language: "zh" | "en" = "zh") {
  return (labels[state] ?? labels.offline)[language];
}
