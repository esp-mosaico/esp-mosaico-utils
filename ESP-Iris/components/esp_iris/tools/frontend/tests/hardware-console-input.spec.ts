import { expect, test } from "@playwright/test";
import { writeFile } from "node:fs/promises";

const targets: { deviceId: string; endpoint: string }[] = JSON.parse(process.env.ESP_IRIS_CONNECTION_TARGETS || "[]");

test("native console commands and replies work on the explicitly selected live devices", async ({ page }, testInfo) => {
  test.skip(!process.env.ESP_IRIS_TEST_URL || !targets.length, "requires explicitly selected devices");
  test.setTimeout(90_000);
  const errors: string[] = [];
  const evidence = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  if (await page.getByLabel("开发口令").isVisible().catch(() => false)) await page.getByRole("button", { name: "进入工作台" }).click();
  for (const target of targets) {
    const inventory = await (await page.request.get("/v2/devices")).json();
    const before = inventory.devices.find((item: any) => item.device_id === target.deviceId);
    expect(before.connected && before.console_available).toBe(true);
    await page.locator(".device-select").filter({ hasText: before.hardware_mac }).click();
    await page.getByRole("button", { name: "输入命令", exact: true }).click();
    const commands = [];
    for (const line of ["iris help", "iris status"]) {
      const since = Date.now() * 1e6;
      const response = page.waitForResponse((item) => item.request().method() === "POST" && item.url().endsWith(`/devices/${target.deviceId}/console`));
      await page.getByLabel("Console 命令").fill(line);
      await page.getByLabel("Console 命令").press("Enter");
      const sent = await response;
      expect(sent.ok(), await sent.text()).toBe(true);
      const result = await sent.json();
      expect(result.console).toMatchObject({ sent: true, completion: "unconfirmed", endpoint: target.endpoint });
      expect(result.console.job_id).toBeUndefined();
      expect(result.operation.params.transport).toBe("console-text");
      const expected = line === "iris help" ? "device identity and health" : `device=${target.deviceId} boot=${before.boot_id_text}`;
      await expect(page.locator(".log-body")).toContainText(expected);
      let liveLogs: any[] = [];
      await expect.poll(async () => {
        const events = await (await page.request.get(`/v2/events?device_id=${target.deviceId}&categories=log`)).json();
        liveLogs = events.events.filter((item: any) => (item.host_receive_wall_ns || item.host_receive_ns) >= since);
        return liveLogs.some((item) => item.text?.includes(expected));
      }).toBe(true);
      commands.push({ line, result, liveLogs });
    }
    const after = await (await page.request.get(`/v2/devices/${target.deviceId}`)).json();
    expect(after.boot_id_text).toBe(before.boot_id_text);
    evidence.push({ before, commands, after });
  }
  await page.screenshot({ path: testInfo.outputPath("native-console.png"), fullPage: true });
  const path = testInfo.outputPath("native-console-evidence.json");
  await writeFile(path, JSON.stringify({ evidence, errors }, null, 2));
  await testInfo.attach("native-console-evidence", { path, contentType: "application/json" });
  expect(errors).toEqual([]);
});
