import { expect, test } from "@playwright/test";

test("switching devices clears old pictures and releases only its own media streams", async ({ page }) => {
  const devices = ["Media A", "Media B"].map((alias, i) => ({ device_id: `media-${i}`, alias, connected: true,
    state: "idle", capability_names: ["audio", "screen"], data_available: true }));
  const actions: string[] = [];
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.routeWebSocket(/\/streams\/(screen|audio)/, () => {});
  await page.route("**/v2/devices**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const device = devices.find((item) => path.startsWith(`/v2/devices/${item.device_id}`));
    if (path === "/v2/devices") await route.fulfill({ json: { devices, demo: false } });
    else if (path.endsWith("/screenshot")) await route.fulfill({ contentType: "image/png",
      body: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=", "base64") });
    else if (path.includes("/mirror/")) {
      actions.push(`${device!.device_id}:${route.request().postDataJSON().channel}:${path.split("/").pop()}`);
      await route.fulfill({ json: {} });
    } else if (device) await route.fulfill({ json: { ...device, stale: false } });
    else await route.continue();
  });
  await page.goto("/");
  if (await page.getByLabel("开发口令").isVisible().catch(() => false)) await page.getByRole("button", { name: "进入工作台" }).click();
  await page.getByRole("button", { name: "截图", exact: true }).click();
  await expect(page.getByAltText("设备实时画面")).toBeVisible();
  await page.locator(".device-select").filter({ hasText: "Media B" }).click();
  await expect(page.getByAltText("设备实时画面")).toHaveCount(0);
  await page.getByRole("button", { name: "启动镜像", exact: true }).click();
  await expect(page.getByRole("button", { name: "停止镜像", exact: true })).toBeVisible();
  await page.locator(".device-select").filter({ hasText: "Media A" }).click();
  await expect.poll(() => actions).toContain("media-1:screen:stop");
  await page.getByRole("button", { name: "录音（最长 60s）", exact: true }).click();
  await expect(page.getByRole("button", { name: /停止录音/ })).toBeVisible();
  await page.locator(".device-select").filter({ hasText: "Media B" }).click();
  await expect.poll(() => actions).toContain("media-0:audio:stop");
  expect(actions).toEqual(["media-1:screen:start", "media-1:screen:stop", "media-0:audio:start", "media-0:audio:stop"]);
  expect(errors).toEqual([]);
});
