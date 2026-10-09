import { expect, test } from "@playwright/test";
import { writeFile } from "node:fs/promises";

// Opt in with explicit identities: never pick an arbitrary attached board.
const targets: { endpoint: string; deviceId: string; baudrate?: number; data?: boolean }[] =
  JSON.parse(process.env.ESP_IRIS_CONNECTION_TARGETS || "[]");

test("mixed real transports connect and disconnect through the workbench", async ({ page }, testInfo) => {
  test.skip(!process.env.ESP_IRIS_TEST_URL || !targets.length, "requires explicit live endpoint/Device ID pairs");
  test.setTimeout(120_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  if (await page.getByLabel("开发口令").isVisible().catch(() => false)) {
    await page.getByRole("button", { name: "进入工作台" }).click();
  }
  await page.getByRole("button", { name: "连接设备", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "连接设备" });
  const devices = async () => (await (await page.request.get("/v2/devices")).json()).devices;
  const evidence = [];
  for (const target of targets) {
    const row = dialog.locator(`[data-endpoint="${target.endpoint}"]`);
    await expect(row).toBeVisible();
    const connect = async () => {
      if (target.baudrate) await row.getByRole("spinbutton").fill(String(target.baudrate));
      await row.getByRole("button", { name: "连接到本项目", exact: true }).click();
      await expect(row.getByRole("button", { name: "断开连接", exact: true })).toBeEnabled({ timeout: 20_000 });
      await expect.poll(async () => (await devices()).find((item: any) => item.device_id === target.deviceId)?.connected).toBe(true);
    };
    if (await row.getByRole("button", { name: "连接到本项目", exact: true }).count()) await connect();
    const before = (await devices()).find((item: any) => item.device_id === target.deviceId);
    expect(before.connected).toBe(true);
    await row.getByRole("button", { name: "断开连接", exact: true }).click();
    await expect(row.getByRole("button", { name: "连接到本项目", exact: true })).toBeEnabled();
    await page.waitForTimeout(3200); // One full inventory refresh; no auto-acquisition after release.
    const released = (await devices()).find((item: any) => item.device_id === target.deviceId);
    expect(released.connected).toBe(false);
    expect(released.state).toBe("discovered");
    expect(released.control_link).toBeNull();
    expect(released.data_link).toBeNull();
    const project = await (await page.request.get("/v2/project")).json();
    expect(project.claims.filter((claim: any) => claim.device_id === target.deviceId)).toHaveLength(0);
    await connect();
    if (target.data) await expect.poll(async () => (await devices()).find((item: any) => item.device_id === target.deviceId)?.data_available).toBe(true);
    const after = (await devices()).find((item: any) => item.device_id === target.deviceId);
    expect(after.boot_id_text).toBe(before.boot_id_text); // Attach/release must not reset hardware.
    evidence.push({ target, before, released, after });
  }
  await dialog.evaluate((element) => { element.scrollTop = 0; });
  await page.screenshot({ path: testInfo.outputPath("connections.png"), fullPage: true });
  await dialog.getByRole("button", { name: "关闭", exact: true }).click();
  await page.screenshot({ path: testInfo.outputPath("devices.png"), fullPage: true });
  const evidencePath = testInfo.outputPath("connection-evidence.json");
  await writeFile(evidencePath, JSON.stringify(evidence, null, 2));
  await testInfo.attach("connection-evidence", { path: evidencePath, contentType: "application/json" });
  expect(errors).toEqual([]);
});
