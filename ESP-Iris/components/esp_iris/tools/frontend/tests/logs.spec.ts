import { expect, test } from "@playwright/test";

test("blank console separators are hidden without altering retained log text", async ({ page }) => {
  let send: (text: string) => void = () => { throw new Error("event socket not connected"); };
  await page.route("**/v2/devices", async (route) => route.fulfill({ json: { demo: true, devices: [{
    device_id: "log-device", alias: "Log device", connected: true, state: "idle", console_available: true,
  }] } }));
  await page.route("**/v2/devices/log-device", async (route) => route.fulfill({ json: { device_id: "log-device", stale: false } }));
  await page.routeWebSocket(/\/v2\/events\/ws/, (socket) => {
    let eventId = 0;
    send = (text) => socket.send(JSON.stringify({ category: "log", kind: "log", device_id: "log-device",
      event_id: ++eventId, text, host_receive_wall_ns: Date.now() * 1e6 }));
    for (const text of ["\r\n", "", " \t\n", "I (1) app: alive\n", "heading\n\n  detail\n"]) send(text);
  });
  await page.goto("/");
  if (await page.getByLabel("开发口令").isVisible().catch(() => false)) await page.getByRole("button", { name: "进入工作台" }).click();
  const rows = page.locator(".log-line code");
  await expect(rows).toHaveCount(2);
  expect(await rows.allTextContents()).toEqual(["I (1) app: alive\n", "heading\n\n  detail\n"]);
  const blanks = page.getByRole("button", { name: "显示空行", exact: true });
  await expect(blanks).toHaveAttribute("aria-pressed", "false");
  await blanks.click();
  await expect(rows).toHaveCount(5);
  expect(await rows.allTextContents()).toEqual(["\r\n", "", " \t\n", "I (1) app: alive\n", "heading\n\n  detail\n"]);
  await page.getByRole("button", { name: "暂停", exact: true }).click();
  send("fresh reply\n");
  await blanks.click();
  await expect(rows).toHaveCount(2);
  await page.getByRole("button", { name: "继续", exact: true }).click();
  await expect(rows).toHaveCount(3);
  await page.getByLabel("搜索日志").fill("detail");
  await expect(rows).toHaveCount(1);
  expect(await rows.textContent()).toBe("heading\n\n  detail\n");
});
