import { useState } from "react";
import { api } from "./api";
import { deviceStateLabel } from "./deviceState";
import type { DeviceState } from "./types";

export type Claim = { owner: string; owner_alive: boolean; device_id: string | null; state: string; transfer_id: string | null };
export type Endpoint = { endpoint: string; state: DeviceState; ownership: Claim | null; present?: boolean;
  path?: string; device_path?: string; product?: string; transport_name?: string; link_role?: string; uart?: boolean;
  baudrate?: number; error?: string | null; pairing?: string; pairing_saved?: boolean;
  pairing_required?: boolean; usb_pairing_available?: boolean };
export type ConnectionAction = (action: string, body: Record<string, unknown>) => Promise<void>;

export function connectionProblem(message: string, dataLink = false): string {
  if (message.includes("requires a pairing token")) return "需要配对：可先通过 USB 配对，或输入设备的配对令牌。";
  if (message.includes("pairing proof was rejected")) return "配对令牌已失效或不匹配，请通过 USB 重新配对或更新令牌。";
  if (/refused|unreachable|timed out|TimeoutError/i.test(message)) {
    return dataLink ? "数据接口不可达：检查设备网络与数据端口；控制接口连通并不代表数据接口可用。"
      : "连接未完成：检查设备是否联网、地址和端口是否可达。";
  }
  return message;
}

export function EndpointConnection({ item, pending, owned, act }: {
  item: Endpoint; pending: boolean; owned: boolean; act: ConnectionAction;
}) {
  const [baudrate, setBaudrate] = useState(String(item.baudrate || 115200));
  const [token, setToken] = useState("");
  const tcp = item.endpoint.startsWith("tcp:");
  const cleanToken = token.trim();
  const validToken = cleanToken ? /^[0-9a-fA-F]{64}$/.test(cleanToken) : !item.pairing_required;
  const validBaud = /^\d+$/.test(baudrate) && Number(baudrate) >= 9600 && Number(baudrate) <= 3000000;
  return <>
    <p>{deviceStateLabel(item.state)}{item.link_role === "data" ? " · 数据链路" : ""}</p>
    {item.error && <p className="rail-error">{connectionProblem(item.error, item.link_role === "data")}</p>}
    {tcp && <p className="section-copy">{item.pairing_saved ? "已配对 · 本机已记住此设备" : item.pairing_required ? "需要配对" : "可使用本机已配置的配对凭据"}</p>}
    {!item.ownership && item.link_role === "data" && <p className="section-copy">数据接口由网关自动验证并绑定，也可单独连接。</p>}
    {!item.ownership && <form className="settings-actions" onSubmit={(event) => {
      event.preventDefault();
      void act("acquire", { endpoint: item.endpoint, ...(item.uart ? { baudrate: Number(baudrate) } : {}),
        ...(cleanToken ? { pairing_token: cleanToken } : {}) }).then(() => setToken(""));
    }}>
      {item.uart && <label>波特率 <input aria-label={`波特率 ${item.device_path || item.endpoint}`} type="number" min="9600" max="3000000" step="1" value={baudrate} disabled={pending} onChange={(event) => setBaudrate(event.target.value)} /></label>}
      {tcp && <label>{item.pairing_saved ? "更新配对令牌（可留空）" : "配对令牌"}
        <input aria-label={`配对令牌 ${item.endpoint}`} type="password" autoComplete="off" value={token}
          required={item.pairing_required} disabled={pending} onChange={(event) => setToken(event.target.value)} />
      </label>}
      <button disabled={pending || item.present === false || item.state === "busy" || item.state === "needs_recovery" || (item.uart && !validBaud) || (tcp && !validToken)}>{item.link_role === "data" ? "连接数据接口" : "连接到本项目"}</button>
    </form>}
    {owned && item.usb_pairing_available && <button disabled={pending} onClick={() => void act("pair", { device_id: item.ownership?.device_id })}>
      {item.pairing_saved ? "通过 USB 更新配对" : "通过 USB 配对"}
    </button>}
    {owned && <button disabled={pending} onClick={() => void act("release", item.ownership?.device_id
      ? { device_id: item.ownership.device_id } : { endpoint: item.endpoint })}>断开连接</button>}
  </>;
}

export function ManualConnection({ pending, act }: { pending: boolean; act: ConnectionAction }) {
  const [endpoint, setEndpoint] = useState("");
  const [baudrate, setBaudrate] = useState("115200");
  const [token, setToken] = useState("");
  const tcp = endpoint.trim().startsWith("tcp:");
  const valid = endpoint.trim() && (tcp ? !token.trim() || /^[0-9a-fA-F]{64}$/.test(token.trim())
    : /^\d+$/.test(baudrate) && Number(baudrate) >= 9600 && Number(baudrate) <= 3000000);
  return <details className="manual-connection"><summary>手动输入连接地址</summary>
    <form onSubmit={(event) => { event.preventDefault(); void act("acquire", {
      endpoint: endpoint.trim(), ...(tcp ? (token.trim() ? { pairing_token: token.trim() } : {}) : { baudrate: Number(baudrate) }),
    }).then(() => setToken("")); }}>
      <label>连接地址<input aria-label="连接地址" placeholder="/dev/ttyUSB0 · COM3 · tcp:192.168.1.10:19772" required value={endpoint} disabled={pending} onChange={(event) => setEndpoint(event.target.value)} /></label>
      {tcp ? <label>配对令牌（已配对可留空）<input aria-label="配对令牌（已配对可留空）" type="password" autoComplete="off" value={token} disabled={pending} onChange={(event) => setToken(event.target.value)} /></label>
        : <label>波特率<input aria-label="手动连接波特率" type="number" min="9600" max="3000000" step="1" value={baudrate} disabled={pending} onChange={(event) => setBaudrate(event.target.value)} /></label>}
      <button disabled={pending || !valid}>连接</button>
      {tcp && <p className="section-copy">连接成功后，本机会记住此设备的令牌。首次使用也可先连接 USB，再点击“通过 USB 配对”。</p>}
    </form>
  </details>;
}

export async function connectionRequest(action: string, body: Record<string, unknown>) {
  if (action === "pair") return api(`/v2/devices/${body.device_id}/pairing`, { method: "POST", body: "{}" });
  if (action === "forget-pairing") return api(`/v2/pairings/${body.device_id}`, { method: "DELETE" });
  await api(`/v2/project/${action}`, { method: "POST", body: JSON.stringify(body) });
}
