import { useEffect, useRef, useState } from "react";
import { api } from "./api";

export default function AudioControls({
  deviceId,
  mode,
}: {
  deviceId: string;
  mode: "develop" | "observe";
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const alive = useRef(true);
  const active = useRef(false);
  const [recording, setRecording] = useState(false);
  const [wav, setWav] = useState<string>("");
  const [seconds, setSeconds] = useState(0);
  const chunks = useRef<Uint8Array[]>([]);
  const socket = useRef<WebSocket | null>(null);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      socket.current?.close();
      if (timer.current) window.clearInterval(timer.current);
      if (active.current) void api(`/v2/devices/${encodeURIComponent(deviceId)}/mirror/stop`, {
        method: "POST", body: JSON.stringify({ channel: "audio" }),
      }).catch(() => undefined);
    };
  }, [deviceId]);
  useEffect(() => () => { if (wav) URL.revokeObjectURL(wav); }, [wav]);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    try { await action(); }
    catch (reason) { if (alive.current) setError(String(reason)); }
    finally { if (alive.current) setBusy(false); }
  }

  async function stop() {
    socket.current?.close();
    socket.current = null;
    if (timer.current) window.clearInterval(timer.current);
    timer.current = null;
    await api(`/v2/devices/${encodeURIComponent(deviceId)}/mirror/stop`, {
      method: "POST",
      body: JSON.stringify({ channel: "audio" }),
      headers: { "Content-Type": "application/json" },
    }).catch(() => undefined);
    active.current = false;
    if (!alive.current) return;
    setRecording(false);
    const pcm = concatenate(chunks.current);
    if (pcm.length) {
      if (wav) URL.revokeObjectURL(wav);
      setWav(
        URL.createObjectURL(
          new Blob([waveFile(pcm, 16000, 1)], { type: "audio/wav" }),
        ),
      );
    }
  }

  async function start() {
    chunks.current = [];
    setSeconds(0);
    await api(`/v2/devices/${encodeURIComponent(deviceId)}/mirror/start`, {
      method: "POST",
      body: JSON.stringify({
        channel: "audio",
        fps: 5,
        description: { sample_rate: 16000, channels: 1, format: 1 },
      }),
      headers: { "Content-Type": "application/json" },
    });
    active.current = true;
    if (!alive.current) { await stop(); return; }
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(
      `${protocol}//${location.host}/v2/devices/${encodeURIComponent(deviceId)}/streams/audio`,
    );
    ws.binaryType = "arraybuffer";
    ws.onmessage = (message) => {
      const bytes = new Uint8Array(message.data as ArrayBuffer);
      if (bytes.length < 4) return;
      const metadataLength = new DataView(bytes.buffer).getUint32(0, true);
      if (metadataLength > bytes.length - 4) return;
      chunks.current.push(bytes.slice(4 + metadataLength));
    };
    socket.current = ws;
    setRecording(true);
    timer.current = window.setInterval(
      () =>
        setSeconds((value) => {
          if (value >= 59) {
            void stop();
            return 60;
          }
          return value + 1;
        }),
      1000,
    );
  }

  async function upload(file?: File) {
    if (!file) return;
    const response = await fetch(
      `/v2/devices/${encodeURIComponent(deviceId)}/audio`,
      {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": file.type || "audio/wav" },
        body: file,
      },
    );
    if (!response.ok) throw new Error("音频上传失败");
  }

  return (
    <div className="audio-controls">
      <span>音频</span>
      {error && <span role="alert">{error}</span>}
      <button disabled={mode === "observe" || busy} onClick={() => void run(recording ? stop : start)}>
        {recording ? `停止录音 ${seconds}s` : "录音（最长 60s）"}
      </button>
      <label className={mode === "observe" ? "disabled" : ""}>
        上传 WAV/PCM
        <input
          type="file"
          accept="audio/wav,.wav,.pcm"
          disabled={mode === "observe" || busy}
          onChange={(event) => { const file = event.target.files?.[0]; void run(() => upload(file)); }}
        />
      </label>
      {wav && (
        <>
          <audio controls src={wav} />
          <a href={wav} download={`esp-iris-${deviceId}.wav`}>
            下载 WAV
          </a>
        </>
      )}
      <small>实时流默认不落盘 · 上传/保存上限 16 MiB</small>
    </div>
  );
}

function concatenate(values: Uint8Array[]) {
  const length = values.reduce((sum, value) => sum + value.length, 0);
  const output = new Uint8Array(length);
  let offset = 0;
  for (const value of values) {
    output.set(value, offset);
    offset += value.length;
  }
  return output;
}

function waveFile(pcm: Uint8Array, sampleRate: number, channels: number) {
  const buffer = new ArrayBuffer(44 + pcm.length);
  const view = new DataView(buffer);
  const write = (offset: number, text: string) =>
    [...text].forEach((character, index) =>
      view.setUint8(offset + index, character.charCodeAt(0)),
    );
  write(0, "RIFF");
  view.setUint32(4, 36 + pcm.length, true);
  write(8, "WAVE");
  write(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, channels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * channels * 2, true);
  view.setUint16(32, channels * 2, true);
  view.setUint16(34, 16, true);
  write(36, "data");
  view.setUint32(40, pcm.length, true);
  new Uint8Array(buffer, 44).set(pcm);
  return buffer;
}

