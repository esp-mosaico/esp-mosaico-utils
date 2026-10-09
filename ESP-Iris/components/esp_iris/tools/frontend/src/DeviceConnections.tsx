import { useEffect, useRef, useState } from "react";
import { connectionRequest } from "./ConnectionControls";
import ProjectSession from "./ProjectSession";
import type { Device } from "./types";

export default function DeviceConnections({ device, sessionId, refresh }: {
  device?: Device; sessionId: string; refresh: () => Promise<void>;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const opener = useRef<HTMLButtonElement | null>(null);
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => { if (open) dialog.current?.showModal(); }, [open]);
  useEffect(() => { setMessage(""); }, [device?.device_id]);
  const owned = device?.owner_session_id === sessionId;
  async function disconnect() {
    if (!device) return;
    setPending(true);
    setMessage("");
    try {
      await connectionRequest("release", { device_id: device.device_id });
      setMessage("已断开连接，端口已释放");
    } catch (error) { setMessage(error instanceof Error ? error.message : String(error)); }
    finally { await refresh(); setPending(false); }
  }
  return <div className="connection-toolbar">
    <button onClick={(event) => { opener.current = event.currentTarget; setOpen(true); }}>连接设备</button>
    {owned && <button disabled={pending} onClick={() => void disconnect()}>{pending ? "正在断开…" : "断开当前设备"}</button>}
    <span>{device?.connected ? "已连接，自动重连已启用" : "连接后可查看实时日志与状态"}</span>
    {message && <span role="status">{message}</span>}
    {open && <dialog ref={dialog} className="connections-dialog" aria-label="连接设备" onCancel={() => setOpen(false)} onClose={() => { setOpen(false); opener.current?.focus(); }}>
      <div className="connection-toolbar"><strong>连接设备</strong><button autoFocus onClick={() => dialog.current?.close()}>关闭</button></div>
      <ProjectSession compact onChanged={refresh} />
    </dialog>}
  </div>;
}
