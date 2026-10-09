import { EndpointConnection, ManualConnection, connectionRequest, type Endpoint } from "./ConnectionControls";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, formatTime } from "./api";

type Session = { session_id: string; project_path: string; alive: boolean };
type Lifecycle = { state: string; idle_remaining_seconds: number | null; idle_timeout_seconds: number;
  clients: { client_id: string; kind: string; command: string; pid: number | null; connected_ns: number; last_seen_ns: number }[];
  keepalive: Record<string, number> };
type Snapshot = { session: Session; sessions: Session[]; endpoints: Endpoint[]; closing: boolean; lifecycle?: Lifecycle; takeovers: { takeover_id: string; target: string; state: string }[] };

export default function ProjectSession({ compact = false, onChanged }: { compact?: boolean; onChanged?: () => Promise<void> }) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState(false);
  const [pollError, setPollError] = useState("");
  const generation = useRef(0);
  const refresh = useCallback(async () => {
    const request = ++generation.current;
    try {
      const value = await api<Snapshot>("/v2/project");
      if (request === generation.current) { setSnapshot(value); setPollError(""); }
    } catch (error) { if (request === generation.current) setPollError(String(error)); }
  }, []);
  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), 2000);
    return () => { ++generation.current; clearInterval(timer); };
  }, [refresh]);
  async function act(action: string, body: Record<string, unknown>) {
    setPending(true);
    setMessage("");
    try {
      await connectionRequest(action, body);
      setMessage(action === "acquire" ? "已连接，设备身份已验证" : action === "release" ? "已断开连接，端口已释放" : "操作完成");
    } catch (error) { setMessage(String(error)); }
    finally { await refresh().catch((error) => setPollError(String(error))); await onChanged?.(); setPending(false); }
  }
  if (!snapshot) return <p role="status">{pollError || "正在发现设备…"}</p>;
  const self = snapshot.session.session_id;
  return <section className="settings-section settings-wide">
    <div className="panel-title"><span>项目会话与设备归属</span></div>
    {!compact && <dl className="settings-dl"><dt>项目</dt><dd>{snapshot.session.project_path}</dd><dt>会话</dt><dd>{self}</dd><dt>状态</dt><dd>{snapshot.closing ? "正在结束" : "运行中"}</dd></dl>}
    {!compact && snapshot.lifecycle && <div aria-label="网关使用者">
      <div className="panel-title"><span>当前使用者</span></div>
      {snapshot.lifecycle.clients.map((client) => <div className="project-endpoint" key={client.client_id}>
        <strong>{client.command}</strong>
        <p>{client.kind} · {client.client_id}{client.pid ? ` · PID ${client.pid}` : ""}</p>
        <p>连接于 {formatTime(client.connected_ns)} · 最近保活 {formatTime(client.last_seen_ns)}</p>
      </div>)}
      {!snapshot.lifecycle.clients.length && <p>没有已登记的客户端。</p>}
      <p className="section-copy">客户端离开且后台工作完成后，空闲 {snapshot.lifecycle.idle_timeout_seconds} 秒自动退出。通过 CLI 重新启动后可再次打开工作台。</p>
      {snapshot.lifecycle.idle_remaining_seconds !== null && <p>退出倒计时：{snapshot.lifecycle.idle_remaining_seconds.toFixed(1)} 秒</p>}
    </div>}
    <p className="section-copy">发现设备不会自动连接。明确连接后，本会话会在设备重启时自动重连；其他项目的设备可主动接管。强制接管会停止镜像和后台任务，等待当前写入安全结束。</p>
    {pollError && <p role="alert" className="rail-error">{pollError}</p>}
    {(pending || message) && <p role="status" className="inline-notice">{pending ? "正在处理连接请求…" : message}</p>}
    {snapshot.endpoints.map((item) => {
      const claim = item.ownership;
      const owned = claim?.owner === self && claim.state === "owned";
      const owner = snapshot.sessions.find((value) => value.session_id === claim?.owner);
      const takeover = snapshot.takeovers.find((value) => value.takeover_id === claim?.transfer_id);
      const canTakeover = claim && claim.owner !== self && claim.owner_alive && claim.state === "owned" && claim.device_id;
      return <div className="project-endpoint" data-endpoint={item.endpoint} key={item.endpoint}>
        <strong>{item.product || item.endpoint}</strong>
        <p>{item.device_path || item.path || item.endpoint} · {item.transport_name || item.endpoint}</p>
        <EndpointConnection item={item} pending={pending || snapshot.closing} owned={owned} act={act} />
        <p>{claim ? `${owner?.project_path || claim.owner} · ${claim.owner_alive ? claim.state : "归属待核对"}` : "未分配"}</p>
        {claim?.device_id && <p>Device ID: {claim.device_id}</p>}
        {claim?.transfer_id && <p>接管 ID: {claim.transfer_id}</p>}
        <div className="settings-actions">
          {canTakeover && <>
            <button disabled={pending || snapshot.closing} onClick={() => void act("takeovers", { device_id: claim.device_id, takeover_id: crypto.randomUUID() })}>接管到本项目</button>
            <button disabled={pending || snapshot.closing} onClick={() => void act("takeovers", { device_id: claim.device_id, takeover_id: crypto.randomUUID(), force: true })}>强制接管</button>
          </>}
          {takeover?.target === self && ["preparing", "offered", "accepting"].includes(takeover.state) && <button disabled={pending || snapshot.closing} onClick={() => void act(`takeovers/${takeover.takeover_id}/resume`, {})}>继续接管</button>}

        </div>
      </div>;
    })}
    {!snapshot.endpoints.length && <p>尚未发现设备。</p>}
    <ManualConnection pending={pending || snapshot.closing} act={act} />
  </section>;
}
