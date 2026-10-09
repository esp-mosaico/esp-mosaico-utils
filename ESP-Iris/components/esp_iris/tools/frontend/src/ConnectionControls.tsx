import { useState } from "react";
import { api } from "./api";
import { deviceStateLabel } from "./deviceState";
import type { DeviceState } from "./types";

export type Claim = { owner: string; owner_alive: boolean; device_id: string | null; state: string; transfer_id: string | null };
export type Endpoint = { endpoint: string; state: DeviceState; ownership: Claim | null; present?: boolean;
  path?: string; device_path?: string; product?: string; transport_name?: string; link_role?: string; uart?: boolean;
  baudrate?: number; error?: string | null };
export type ConnectionAction = (action: string, body: Record<string, unknown>) => Promise<void>;

export function EndpointConnection({ item, pending, owned, act }: {
  item: Endpoint; pending: boolean; owned: boolean; act: ConnectionAction;
}) {
  const [baudrate, setBaudrate] = useState(String(item.baudrate || 115200));
  const validBaud = /^\d+$/.test(baudrate) && Number(baudrate) >= 9600 && Number(baudrate) <= 3000000;
  return <>
    <p>{deviceStateLabel(item.state)}{item.link_role === "data" ? " · 数据链路" : ""}</p>
    {item.error && <p className="rail-error">{item.error}</p>}
    {!item.ownership && item.link_role === "data" && <p className="section-copy">数据接口由网关自动验证并绑定，也可单独连接。</p>}
    {!item.ownership && <form className="settings-actions" onSubmit={(event) => {
      event.preventDefault();
      void act("acquire", { endpoint: item.endpoint, ...(item.uart ? { baudrate: Number(baudrate) } : {}) });
    }}>
      {item.uart && <label>波特率 <input aria-label={`波特率 ${item.device_path || item.endpoint}`} type="number" min="9600" max="3000000" step="1" value={baudrate} disabled={pending} onChange={(event) => setBaudrate(event.target.value)} /></label>}
      <button disabled={pending || item.present === false || item.state === "busy" || item.state === "needs_recovery" || (item.uart && !validBaud)}>{item.link_role === "data" ? "连接数据接口" : "连接到本项目"}</button>
    </form>}
    {owned && <button disabled={pending} onClick={() => void act("release", item.ownership?.device_id
      ? { device_id: item.ownership.device_id } : { endpoint: item.endpoint })}>断开连接</button>}
  </>;
}

export function ManualConnection({ pending, act }: { pending: boolean; act: ConnectionAction }) {
  const [endpoint, setEndpoint] = useState("");
  const [baudrate, setBaudrate] = useState("115200");
  const [token, setToken] = useState("");
  const tcp = endpoint.trim().startsWith("tcp:");
  const valid = endpoint.trim() && (tcp ? !token || /^[0-9a-fA-F]{64}$/.test(token)
    : /^\d+$/.test(baudrate) && Number(baudrate) >= 9600 && Number(baudrate) <= 3000000);
  return <details className="manual-connection"><summary>手动输入连接地址</summary>
    <form onSubmit={(event) => { event.preventDefault(); void act("acquire", {
      endpoint: endpoint.trim(), ...(tcp ? (token ? { pairing_token: token } : {}) : { baudrate: Number(baudrate) }),
    }); }}>
      <label>连接地址<input aria-label="连接地址" placeholder="/dev/ttyUSB0 · COM3 · tcp:192.168.1.10:29772" required value={endpoint} disabled={pending} onChange={(event) => setEndpoint(event.target.value)} /></label>
      {tcp ? <label>配对令牌（可选）<input aria-label="配对令牌（可选）" type="password" autoComplete="off" value={token} disabled={pending} onChange={(event) => setToken(event.target.value)} /></label>
        : <label>波特率<input aria-label="手动连接波特率" type="number" min="9600" max="3000000" step="1" value={baudrate} disabled={pending} onChange={(event) => setBaudrate(event.target.value)} /></label>}
      <button disabled={pending || !valid}>连接</button>
    </form>
  </details>;
}

export async function connectionRequest(action: string, body: Record<string, unknown>) {
  await api(`/v2/project/${action}`, { method: "POST", body: JSON.stringify(body) });
}
