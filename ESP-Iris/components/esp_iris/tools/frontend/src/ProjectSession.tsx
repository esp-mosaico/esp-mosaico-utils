import { useEffect, useState } from "react";
import { api } from "./api";

type Session = { session_id: string; project_path: string; alive: boolean };
type Claim = { owner: string; owner_alive: boolean; device_id: string | null; state: string; transfer_id: string | null };
type Endpoint = { endpoint: string; state: string; ownership: Claim | null };
type Snapshot = { session: Session; sessions: Session[]; endpoints: Endpoint[]; closing: boolean; transfers: { transfer_id: string; target: string; state: string }[] };

export default function ProjectSession() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState(false);
  const [target, setTarget] = useState("");
  async function refresh() { setSnapshot(await api<Snapshot>("/v1/project")); }
  useEffect(() => {
    let alive = true;
    const update = () => { void api<Snapshot>("/v1/project").then((value) => { if (alive) setSnapshot(value); }).catch(() => {}); };
    update();
    const timer = setInterval(update, 2000);
    return () => { alive = false; clearInterval(timer); };
  }, []);
  async function act(action: string, body: Record<string, unknown>) {
    setPending(true);
    setMessage("");
    try {
      await api(`/v1/project/${action}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      setMessage("操作完成");
    } catch (error) { setMessage(String(error)); }
    finally { setPending(false); await refresh().catch(() => {}); }
  }
  if (!snapshot) return null;
  const self = snapshot.session.session_id;
  const targets = snapshot.sessions.filter((item) => item.alive && item.session_id !== self);
  return <section className="settings-section settings-wide">
    <div className="panel-title"><span>项目会话与设备归属</span></div>
    <dl className="settings-dl"><dt>项目</dt><dd>{snapshot.session.project_path}</dd><dt>会话</dt><dd>{self}</dd><dt>状态</dt><dd>{snapshot.closing ? "正在结束" : "运行中"}</dd></dl>
    <p className="section-copy">发现设备不会自动连接。明确连接后，本会话会在设备重启时自动重连；转让后由目标会话接管。</p>
    <label className="inline-form project-target"><span>转让目标</span><select aria-label="转让目标会话" value={target} onChange={(event) => setTarget(event.target.value)}><option value="">选择项目会话</option>{targets.map((item) => <option key={item.session_id} value={item.session_id}>{item.project_path} · {item.session_id.slice(0, 8)}</option>)}</select></label>
    {message && <p role="status" className="inline-notice">{message}</p>}
    {snapshot.endpoints.map((item) => {
      const claim = item.ownership;
      const owned = claim?.owner === self && claim.state === "owned";
      const owner = snapshot.sessions.find((value) => value.session_id === claim?.owner);
      const transfer = snapshot.transfers.find((value) => value.transfer_id === claim?.transfer_id);
      return <div className="project-endpoint" key={item.endpoint}>
        <strong>{item.endpoint}</strong>
        <p>{claim ? `${owner?.project_path || claim.owner} · ${claim.owner_alive ? claim.state : "归属待核对"}` : "未分配"}</p>
        {claim?.device_id && <p>Device ID: {claim.device_id}</p>}
        {claim?.transfer_id && <p>Transfer ID: {claim.transfer_id}</p>}
        <div className="settings-actions">
          {!claim && <button disabled={pending || snapshot.closing} onClick={() => void act("acquire", { endpoint: item.endpoint })}>连接到本项目</button>}
          {owned && <button disabled={pending || snapshot.closing} onClick={() => void act("release", { endpoint: item.endpoint })}>释放设备</button>}
          {owned && claim.device_id && <button disabled={pending || !target || snapshot.closing} onClick={() => void act("transfer", { device_id: claim.device_id, target_session_id: target, transfer_id: crypto.randomUUID() })}>转让设备</button>}
          {transfer?.target === self && ["preparing", "offered", "accepting"].includes(transfer.state) && <button disabled={pending || snapshot.closing} onClick={() => void act("accept", { transfer_id: claim?.transfer_id })}>尝试接收转让</button>}
        </div>
      </div>;
    })}
    {!snapshot.endpoints.length && <p>尚未发现设备。</p>}
  </section>;
}
