import { expect, test, type Page } from "@playwright/test";

async function openWorkbench(page: Page) {
  await page.goto("/");
  if (await page.getByLabel("开发口令").isVisible().catch(() => false)) {
    await page.getByRole("button", { name: "进入工作台" }).click();
  }
}

const session = { session_id: "web-session", project_path: "/test/project", alive: true };
const deviceId = "00112233445566778899aabbccddeeff";

test("device page discovers UART, retries errors and releases a whole device", async ({ page }) => {
  let connected = false;
  let attempts = 0;
  const actions: { action: string; body: Record<string, unknown> }[] = [];
  await page.route("**/v2/health", async (route) => {
    await route.fulfill({ json: { project_session: session, system_update_trust_configured: false } });
  });
  await page.route("**/v2/devices", async (route) => route.fulfill({ json: { devices: [{ device_id: deviceId,
    suggested_alias: "UART board", endpoint: "usb:location=uart", connected, cached: !connected,
    state: connected ? "idle" : "discovered", owner_session_id: connected ? session.session_id : null,
    // Old servers/caches must not make the workspace show a live control link.
    control_link: { session_id: 1 }, data_available: true }], demo: false } }));
  await page.route(`**/v2/devices/${deviceId}`, async (route) => route.fulfill({ json: {
    device_id: deviceId, connected, state: "idle", stale: false, uptime_us: 2000000,
  } }));
  await page.route("**/v2/project**", async (route) => {
    if (route.request().method() === "POST") {
      const action = new URL(route.request().url()).pathname.split("/").pop()!;
      const body = route.request().postDataJSON();
      actions.push({ action, body });
      if (action === "acquire" && ++attempts === 1) {
        await route.fulfill({ status: 400, json: { error: { message: "HELLO timeout: check baud rate" } } });
        return;
      }
      connected = action === "acquire";
      await route.fulfill({ json: { ok: true } });
      return;
    }
    await route.fulfill({ json: { session, sessions: [session], closing: false, takeovers: [], endpoints: [
      { endpoint: "usb:location=uart", device_path: "/dev/ttyUSB0", product: "CP2102N", uart: true,
        present: true, state: connected ? "idle" : "discovered", ownership: connected ? {
          owner: session.session_id, owner_alive: true, state: "owned", device_id: deviceId,
        } : null },
      { endpoint: "usb:location=data", product: "ESP-Iris data", link_role: "data", present: true, state: "discovered", ownership: null },
      { endpoint: "usb:location=rom", product: "ROM board", present: true, state: "needs_recovery", ownership: null },
    ] } });
  });
  await openWorkbench(page);
  await expect(page.locator(".heading-status")).toContainText("控制：未连接");
  await expect(page.locator(".heading-status")).toContainText("数据：未连接");
  await expect(page.locator(".stale-flag")).toBeVisible();
  await page.getByRole("button", { name: "连接设备", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "连接设备" });
  const uart = dialog.locator('[data-endpoint="usb:location=uart"]');
  await expect(uart).toContainText("已发现 · 未连接");
  await expect(dialog.locator('[data-endpoint="usb:location=data"]').getByRole("button", { name: "连接数据接口" })).toBeEnabled();
  await expect(dialog.locator('[data-endpoint="usb:location=rom"]').getByRole("button")).toBeDisabled();
  await uart.getByLabel("波特率 /dev/ttyUSB0").fill("74880");
  await uart.getByRole("button", { name: "连接到本项目" }).click();
  await expect(dialog.getByRole("status")).toContainText("HELLO timeout");
  await expect(uart.getByRole("button", { name: "连接到本项目" })).toBeEnabled();
  await uart.getByRole("button", { name: "连接到本项目" }).click();
  await expect(uart.getByRole("button", { name: "断开连接", exact: true })).toBeVisible();
  expect(actions[1]).toEqual({ action: "acquire", body: { endpoint: "usb:location=uart", baudrate: 74880 } });
  await dialog.getByRole("button", { name: "关闭", exact: true }).click();
  await page.getByRole("button", { name: "断开当前设备", exact: true }).click();
  await expect(page.locator(".heading-status")).toContainText("已发现 · 未连接");
  expect(actions[2]).toEqual({ action: "release", body: { device_id: deviceId } });
  await expect(page.getByRole("button", { name: "断开当前设备", exact: true })).toHaveCount(0);
});

test("manual TCP connection sends the session token and prevents duplicate requests", async ({ page }) => {
  let finish: (() => void) | undefined;
  let posts = 0;
  await page.route("**/v2/health", async (route) => route.fulfill({ json: { project_session: session } }));
  await page.route("**/v2/project**", async (route) => {
    if (route.request().method() === "POST") {
      posts += 1;
      expect(route.request().postDataJSON()).toEqual({ endpoint: "tcp:192.0.2.1:29772", pairing_token: "ab".repeat(32) });
      await new Promise<void>((resolve) => { finish = resolve; });
      await route.fulfill({ json: {} });
    } else await route.fulfill({ json: { session, sessions: [], endpoints: [], takeovers: [], closing: false } });
  });
  await openWorkbench(page);
  await page.getByRole("button", { name: "连接设备", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByText("手动输入连接地址", { exact: true }).click();
  await dialog.getByLabel("连接地址", { exact: true }).fill("tcp:192.0.2.1:29772");
  await dialog.getByLabel("配对令牌（可选）").fill("ab".repeat(32));
  await dialog.getByRole("button", { name: "连接", exact: true }).click();
  await expect(dialog.getByRole("button", { name: "连接", exact: true })).toBeDisabled();
  await expect.poll(() => posts).toBe(1);
  finish!();
  await expect(dialog.getByRole("button", { name: "连接", exact: true })).toBeEnabled();
});

test("late status responses cannot overwrite the selected device", async ({ page }) => {
  const devices = ["Device A", "Device B"].map((name, i) => ({ device_id: `device-${i}`, alias: name, connected: true, state: "idle" }));
  let finish: (() => void) | undefined;
  await page.route("**/v2/devices", async (route) => route.fulfill({ json: { devices, demo: false } }));
  await page.route("**/v2/devices/device-0", async (route) => {
    await new Promise<void>((resolve) => { finish = resolve; });
    await route.fulfill({ json: { ...devices[0], uptime_us: 999000000, stale: false } });
  });
  await page.route("**/v2/devices/device-1", async (route) => route.fulfill({ json: { ...devices[1], uptime_us: 7000000, stale: false } }));
  await openWorkbench(page);
  await expect.poll(() => Boolean(finish)).toBe(true);
  await page.locator(".device-select").filter({ hasText: "Device B" }).click();
  await expect(page.locator(".metric-strip")).toContainText("7 s");
  finish!();
  await page.waitForTimeout(150);
  await expect(page.locator(".metric-strip")).toContainText("7 s");
  await expect(page.locator(".metric-strip")).not.toContainText("999 s");
});

test("failed mode switch restores the button and shows the error", async ({ page }) => {
  await page.route("**/v2/mode", async (route) => {
    if (route.request().method() === "PUT") await route.fulfill({ status: 409, json: { error: { message: "Device operation still running" } } });
    else await route.continue();
  });
  await openWorkbench(page);
  await page.locator(".mode-switch").click();
  await expect(page.locator(".global-error")).toContainText("Device operation still running");
  await expect(page.locator(".mode-switch")).toBeEnabled();
  await expect(page.locator(".mode-switch")).not.toContainText("切换中");
});
