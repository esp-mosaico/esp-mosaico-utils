import { expect, test, type Page } from "@playwright/test";

async function open(page: Page) {
  await page.goto("/");
  if (await page.getByLabel("开发口令").isVisible().catch(() => false)) await page.getByRole("button", { name: "进入工作台" }).click();
}

test("log input sends text, displays returned logs and preserves history drafts", async ({ page }) => {
  const posts: any[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/console")) posts.push(request.postDataJSON());
  });
  await open(page);
  await page.locator(".device-select").filter({ hasText: "Iris Alpha" }).click();
  await page.getByRole("button", { name: "输入命令", exact: true }).click();
  const input = page.getByLabel("Console 命令");
  await expect(input).toBeFocused();
  const inputBox = await input.boundingBox();
  const sendBox = await page.getByRole("button", { name: "发送", exact: true }).boundingBox();
  expect(inputBox && sendBox).toBeTruthy();
  expect(Math.abs(inputBox!.y - sendBox!.y)).toBeLessThan(5);
  expect(sendBox!.width).toBeGreaterThan(40);
  await input.fill("iris help");
  await input.press("Enter");
  await expect(page.locator(".console-input [role=status]")).toHaveText("已发送：iris help");
  await expect(page.locator(".log-body")).toContainText("iris status  - device identity and health");
  await expect(page.locator(".console-input")).not.toContainText("job");
  await input.fill("unsent draft");
  await input.press("ArrowUp");
  await expect(input).toHaveValue("iris help");
  await input.press("ArrowDown");
  await expect(input).toHaveValue("unsent draft");
  await input.fill("字".repeat(86));
  await expect(page.getByRole("button", { name: "发送", exact: true })).toBeDisabled();
  await expect(page.locator(".console-input [role=alert]")).toContainText("255");
  expect(posts).toEqual([{ line: "iris help" }]);
});

test("failed sends retain input without automatically replaying the command", async ({ page }) => {
  let calls = 0;
  await page.route("**/v2/devices/*/console", async (route) => {
    calls++;
    await route.fulfill({ status: 409, json: { error: { message: "control link disconnected" } } });
  });
  await open(page);
  await page.locator(".device-select").filter({ hasText: "Iris Alpha" }).click();
  const input = page.getByLabel("Console 命令");
  await input.fill("iris status");
  await input.press("Enter");
  await expect(page.locator(".console-input [role=alert]")).toContainText("control link disconnected");
  await expect(input).toHaveValue("iris status");
  await expect(input).toBeEnabled();
  await page.waitForTimeout(300);
  expect(calls).toBe(1);
  await page.locator(".device-select").filter({ hasText: "Camera Bench" }).click();
  await expect(page.getByLabel("Console 命令")).toHaveValue("");
  await expect(page.locator(".console-input [role=alert]")).toHaveCount(0);
});

for (const condition of ["offline", "data-only", "observe"]) {
  test(`console input cannot write while ${condition}`, async ({ page }) => {
    await page.route("**/v2/devices", async (route) => route.fulfill({ json: { demo: false, devices: [{
      device_id: "only", alias: "Only device", connected: condition !== "offline", state: "idle",
      console_available: condition !== "data-only", data_available: true,
    }] } }));
    await page.route("**/v2/devices/only", async (route) => route.fulfill({ json: { device_id: "only", stale: false } }));
    await page.route("**/v2/mode", async (route) => route.fulfill({ json: { mode: condition === "observe" ? "observe" : "develop", transitioning: false } }));
    await open(page);
    await expect(page.getByLabel("Console 命令")).toBeDisabled();
    await expect(page.getByRole("button", { name: "发送", exact: true })).toBeDisabled();
  });
}
