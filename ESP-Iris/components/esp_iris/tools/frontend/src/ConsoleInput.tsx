import { useRef, useState, type FormEvent } from "react";
import { api } from "./api";

const MAX_LINE_BYTES = 255;
const HISTORY_LIMIT = 32;

type ConsoleResult = { console: { sent: boolean; completion: "unconfirmed" } | null };

export default function ConsoleInput({ deviceId, disabledReason }: { deviceId: string; disabledReason: string }) {
  const [line, setLine] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [history, setHistory] = useState<string[]>([]);
  const [historyIndex, setHistoryIndex] = useState(-1);
  const draft = useRef("");
  const input = useRef<HTMLInputElement>(null);
  const byteLength = new TextEncoder().encode(line).length;
  const tooLong = byteLength > MAX_LINE_BYTES;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (disabledReason || busy || !line.trim() || tooLong) return;
    const command = line;
    setBusy(true);
    setMessage("");
    setError("");
    try {
      const result = await api<ConsoleResult>(`/v2/devices/${encodeURIComponent(deviceId)}/console`, {
        method: "POST", body: JSON.stringify({ line: command }),
        headers: { "X-Operation-ID": crypto.randomUUID() },
      });
      if (!result.console?.sent) throw new Error("命令未确认发送，请检查操作记录后再决定是否重试。");
      setMessage(`已发送：${command}`);
      setHistory((current) => [command, ...current.filter((item) => item !== command)].slice(0, HISTORY_LIMIT));
      setHistoryIndex(-1);
      setLine("");
      draft.current = "";
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setBusy(false); requestAnimationFrame(() => input.current?.focus({ preventScroll: true })); }
  }

  function navigateHistory(direction: number) {
    if (!history.length) return;
    if (historyIndex < 0) draft.current = line;
    const next = Math.max(-1, Math.min(history.length - 1, historyIndex + direction));
    setHistoryIndex(next);
    setLine(next < 0 ? draft.current : history[next]);
  }

  return <div className="console-input">
    <form className="console-form" onSubmit={submit}>
      <span aria-hidden="true">&gt;</span>
      <input ref={input} id={`console-input-${deviceId}`} aria-label="Console 命令" autoComplete="off" spellCheck={false}
        placeholder="输入设备命令，例如 iris help 或 iris status" disabled={Boolean(disabledReason) || busy}
        value={line} onChange={(event) => { setLine(event.target.value); setHistoryIndex(-1); }}
        onKeyDown={(event) => {
          if (event.nativeEvent.isComposing) return;
          if (event.key === "ArrowUp" || event.key === "ArrowDown") {
            event.preventDefault(); navigateHistory(event.key === "ArrowUp" ? 1 : -1);
          }
          if (event.key === "Enter" && event.repeat) event.preventDefault();
        }} />
      <small className={tooLong ? "rail-error" : ""}>{byteLength}/{MAX_LINE_BYTES} B</small>
      <button className="primary-button" disabled={Boolean(disabledReason) || busy || !line.trim() || tooLong}>{busy ? "发送中…" : "发送"}</button>
    </form>
    <p className="console-note">{disabledReason || "Enter 发送，↑↓ 查看历史。发送成功仅表示文本已写入；执行结果见设备日志。"}</p>
    {message && <p role="status" className="console-note">{message}</p>}
    {(error || tooLong) && <p role="alert" className="rail-error">{tooLong ? "命令超过 255 个 UTF-8 字节" : error}</p>}
  </div>;
}
