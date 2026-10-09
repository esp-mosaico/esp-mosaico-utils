import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { appendGatewayEvent, nextReconnectDelay } from "./eventState";
import type { Audit, Device, DeviceStatus, GatewayEvent, GatewayHealth, Operation } from "./types";

type AuthState = { required: boolean; configured: boolean; authenticated: boolean; actor?: { type: string; name: string } };
type ModeState = { mode: "develop" | "observe"; transitioning: boolean };

export function useGateway() {
  const [auth, setAuth] = useState<AuthState | null>(null);
  const [mode, setModeState] = useState<ModeState>({ mode: "develop", transitioning: false });
  const [devices, setDevices] = useState<Device[]>([]);
  const [selectedId, setSelectedId] = useState<string>("");
  const [status, setStatus] = useState<DeviceStatus | null>(null);
  const [operations, setOperations] = useState<Operation[]>([]);
  const [audits, setAudits] = useState<Audit[]>([]);
  const [events, setEvents] = useState<GatewayEvent[]>([]);
  const [demo, setDemo] = useState(false);
  const [health, setHealth] = useState<GatewayHealth>({ system_update_trust_configured: false });
  const [error, setError] = useState<string>("");
  const [connectionError, setConnectionError] = useState<string>("");
  const cursor = useRef(0);
  const refreshGeneration = useRef(0);
  const statusGeneration = useRef(0);
  const modePending = useRef(false);

  const refreshAuth = useCallback(async () => {
    const value = await api<AuthState>("/v2/auth/state");
    setAuth(value);
    return value;
  }, []);

  const refresh = useCallback(async () => {
    const generation = ++refreshGeneration.current;
    try {
      const [modeData, deviceData, operationData, auditData, healthData] = await Promise.all([
        api<ModeState>("/v2/mode"),
        api<{ devices: Device[]; demo: boolean }>("/v2/devices"),
        api<{ operations: Operation[] }>("/v2/operations"),
        api<{ audits: Audit[] }>("/v2/system-audit"),
        api<GatewayHealth>("/v2/health"),
      ]);
      if (generation !== refreshGeneration.current) return;
      setModeState({ ...modeData, transitioning: modePending.current || modeData.transitioning });
      setDevices(deviceData.devices);
      setDemo(deviceData.demo);
      setOperations(operationData.operations);
      setAudits(auditData.audits);
      setHealth(healthData);
      setSelectedId((current) => deviceData.devices.some((device) => device.device_id === current)
        ? current : (deviceData.devices.find((device) => device.connected !== false) || deviceData.devices[0])?.device_id || "");
      setError("");
    } catch (reason) {
      if (generation === refreshGeneration.current) setError(reason instanceof Error ? reason.message : String(reason));
    }
  }, []);

  const refreshStatus = useCallback(async () => {
    const generation = ++statusGeneration.current;
    if (!selectedId) {
      setStatus(null);
      return;
    }
    const selected = devices.find((device) => device.device_id === selectedId);
    if (selected?.connected === false) {
      setStatus({ ...selected, stale: true, mode: mode.mode });
      return;
    }
    try {
      const result = await api<DeviceStatus>(`/v2/devices/${encodeURIComponent(selectedId)}`);
      if (generation === statusGeneration.current) setStatus(result);
    } catch (reason) {
      if (generation !== statusGeneration.current) return;
      setStatus(null);
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }, [selectedId, devices, mode.mode]);

  useEffect(() => {
    refreshAuth().catch(() => setAuth({ required: true, configured: true, authenticated: false }));
  }, [refreshAuth]);

  useEffect(() => {
    if (!auth?.authenticated) return;
    refresh();
    const timer = window.setInterval(refresh, 3000);
    return () => window.clearInterval(timer);
  }, [auth?.authenticated, refresh]);

  useEffect(() => {
    if (!auth?.authenticated || !selectedId) return;
    refreshStatus();
    const timer = window.setInterval(refreshStatus, 2500);
    return () => { ++statusGeneration.current; window.clearInterval(timer); };
  }, [auth?.authenticated, refreshStatus, selectedId]);

  useEffect(() => {
    if (!auth?.authenticated) return;
    let closed = false;
    let socket: WebSocket | null = null;
    let refreshTimer: number | null = null;
    let retryTimer: number | null = null;
    let retry = 500;

    const connect = () => {
      const protocol = location.protocol === "https:" ? "wss:" : "ws:";
      if (closed) return;
      socket = new WebSocket(`${protocol}//${location.host}/v2/events/ws?cursor=${cursor.current}&client=workbench`);
      socket.onopen = () => { retry = 500; setConnectionError(""); };
      socket.onmessage = (message) => {
        const item = JSON.parse(message.data) as GatewayEvent;
        if (item.kind === "project_client") return;
        if (item.event_id) cursor.current = Math.max(cursor.current, item.event_id);
        setEvents((current) => appendGatewayEvent(current, item));
        if (item.category === "operation") {
          if (refreshTimer != null) window.clearTimeout(refreshTimer);
          refreshTimer = window.setTimeout(() => { refreshTimer = null; void refresh(); }, 100);
        }
      };
      socket.onclose = () => {
        if (!closed) {
          setConnectionError("工作台连接已断开；如网关已退出，请通过 CLI 重新启动并打开新地址。");
          retryTimer = window.setTimeout(connect, retry);
          retry = nextReconnectDelay(retry);
        }
      };
    };
    connect();
    return () => {
      closed = true;
      if (refreshTimer != null) window.clearTimeout(refreshTimer);
      if (retryTimer != null) window.clearTimeout(retryTimer);
      socket?.close();
    };
  }, [auth?.authenticated, refresh]);

  const setMode = useCallback(async (value: "develop" | "observe") => {
    modePending.current = true;
    setModeState((current) => ({ ...current, transitioning: true }));
    try {
      const result = await api<ModeState>("/v2/mode", { method: "PUT", body: JSON.stringify({ mode: value }), headers: { "Content-Type": "application/json" } });
      setModeState({ ...result, transitioning: true });
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      modePending.current = false;
      setModeState((current) => ({ ...current, transitioning: false }));
    }
  }, [refresh]);

  const removeDevice = useCallback(async (deviceId: string) => {
    await api<{ removed: boolean }>(`/v2/devices/${encodeURIComponent(deviceId)}`, { method: "DELETE" });
    await refresh();
  }, [refresh]);

  const selected = devices.find((device) => device.device_id === selectedId);
  const visibleStatus = selected?.connected === false ? { ...selected, stale: true, mode: mode.mode }
    : status?.device_id === selectedId ? status : null;

  return {
    auth,
    setAuth,
    refreshAuth,
    mode,
    setMode,
    devices,
    selectedId,
    setSelectedId,
    status: visibleStatus,
    operations,
    audits,
    events,
    demo,
    health,
    error: connectionError || error,
    refresh,
    refreshStatus,
    removeDevice,
  };
}
