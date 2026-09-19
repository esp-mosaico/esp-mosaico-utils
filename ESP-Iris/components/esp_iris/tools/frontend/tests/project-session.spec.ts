import { expect, test } from "@playwright/test";

test("project ownership requires an explicit claim and transfers to the selected session", async ({ page }) => {
  const sessions = [
    { session_id: "session-a", project_path: "/projects/a", alive: true },
    { session_id: "session-b", project_path: "/projects/b", alive: true },
  ];
  let owner = "";
  const actions: { action: string; body: Record<string, unknown> }[] = [];
  await page.route("**/v1/health", async (route) => {
    const response = await route.fetch();
    await route.fulfill({ json: { ...await response.json(), project_session: sessions[0] } });
  });
  await page.route("**/v1/project**", async (route) => {
    const request = route.request();
    if (request.method() === "POST") {
      const action = new URL(request.url()).pathname.split("/").pop()!;
      const body = request.postDataJSON();
      actions.push({ action, body });
      owner = action === "acquire" ? "session-a" : action === "transfer" ? String(body.target_session_id) : "";
      await route.fulfill({ json: { ok: true } });
      return;
    }
    await route.fulfill({ json: {
      session: sessions[0], sessions, closing: false, transfers: [],
      lifecycle: { state: "running", idle_remaining_seconds: null, idle_timeout_seconds: 10,
        clients: [{ client_id: "client-run", kind: "run", command: "iris run", pid: 1234,
          connected_ns: 1_700_000_000_000_000_000, last_seen_ns: 1_700_000_000_000_000_000 }], keepalive: { clients: 1 } },
      endpoints: [{ endpoint: "usb:location=test", state: "discovered", ownership: owner ? {
        owner, owner_alive: true, device_id: "00112233445566778899aabbccddeeff", state: "owned", transfer_id: null,
      } : null }],
    } });
  });
  await page.goto("/");
  const password = page.getByLabel("开发口令");
  if (await password.isVisible().catch(() => false)) {
    await page.getByRole("button", { name: "进入工作台" }).click();
  }
  await page.getByRole("button", { name: "设置", exact: true }).click();
  await expect(page.getByText("项目会话与设备归属", { exact: true })).toBeVisible();
  await expect(page.getByLabel("网关使用者")).toContainText("iris run");
  await expect(page.getByLabel("网关使用者")).toContainText("PID 1234");
  await expect(page.getByRole("button", { name: "连接到本项目" })).toBeVisible();
  expect(actions).toEqual([]);
  await page.getByRole("button", { name: "连接到本项目" }).click();
  await expect(page.getByRole("button", { name: "释放设备" })).toBeVisible();
  expect(actions[0]).toEqual({ action: "acquire", body: { endpoint: "usb:location=test" } });
  await expect(page.getByRole("button", { name: "转让设备" })).toBeDisabled();
  await page.getByLabel("转让目标会话").selectOption("session-b");
  await page.screenshot({ path: process.env.ESP_IRIS_PROJECT_SCREENSHOT || "/tmp/esp-iris-project-session.png", fullPage: true });
  await page.getByRole("button", { name: "转让设备" }).click();
  await expect(page.getByRole("button", { name: "释放设备" })).toHaveCount(0);
  expect(actions[1].action).toBe("transfer");
  expect(actions[1].body.target_session_id).toBe("session-b");
  expect(actions[1].body.transfer_id).toMatch(/^[0-9a-f-]{36}$/);
  await expect(page.getByText("/projects/b · owned", { exact: true })).toBeVisible();
});

test("transferred device history stays readable without polling its former owner", async ({ page }) => {
  const history = { device_id: "old-device", suggested_alias: "Transferred device", connected: false, cached: true };
  const current = { device_id: "current-device", suggested_alias: "Current device", connected: true, cached: false };
  let forbiddenRequests = 0;
  await page.route("**/v1/devices**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/v1/devices") {
      await route.fulfill({ json: { demo: false, devices: [history, current] } });
    } else if (path === "/v1/devices/old-device") {
      forbiddenRequests += 1;
      await route.fulfill({ status: 409, json: { message: "device belongs to another project" } });
    } else if (path === "/v1/devices/current-device") {
      await route.fulfill({ json: { ...current, stale: false, mode: "develop" } });
    } else {
      await route.continue();
    }
  });
  await page.goto("/");
  if (await page.getByLabel("开发口令").isVisible().catch(() => false)) {
    await page.getByRole("button", { name: "进入工作台" }).click();
  }
  await expect(page.getByRole("heading", { name: "Current device", exact: true })).toBeVisible();
  await page.locator(".device-select").filter({ hasText: "Transferred device" }).click();
  await expect(page.getByRole("heading", { name: "Transferred device", exact: true })).toBeVisible();
  await page.waitForTimeout(2800);
  expect(forbiddenRequests).toBe(0);
  await expect(page.locator(".global-error")).toHaveCount(0);
});
