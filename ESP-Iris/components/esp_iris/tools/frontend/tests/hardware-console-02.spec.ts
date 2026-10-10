import { expect, test } from "@playwright/test";

const baseURL = process.env.ESP_IRIS_E2E_BASE_URL;
const deviceId = process.env.ESP_IRIS_E2E_DEVICE_ID;
const service = process.env.ESP_IRIS_E2E_RPC_SERVICE;
const method = process.env.ESP_IRIS_E2E_RPC_METHOD;

test("installed 0.2 device: live identity, RPC, screenshot, available mirror and records", async ({ page, request }, testInfo) => {
  test.skip(!baseURL || !deviceId || !service || !method, "explicit managed hardware Gateway and read-only RPC required");
  test.setTimeout(90_000);
  const initialResponse = await request.get(`${baseURL}/v2/devices/${deviceId}`);
  expect(initialResponse.ok()).toBeTruthy();
  const initial = await initialResponse.json();
  expect(initial.device_id).toBe(deviceId);
  expect(initial.stale).not.toBe(true);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("response", (response) => {
    if (new URL(response.url()).pathname.startsWith("/v2/") && !response.ok()) {
      errors.push(`${response.status()} ${new URL(response.url()).pathname}`);
    }
  });
  await page.goto(baseURL!);
  const card = page.locator(".device-select").filter({ hasText: initial.hardware_mac });
  await expect(card).toHaveCount(1);
  await card.click();
  await expect(page.getByText("控制：已连接", { exact: true })).toBeVisible();
  await page.locator("summary").filter({ hasText: "更多操作" }).click();
  await page.getByRole("button", { name: "原始 RPC", exact: true }).click();
  await page.getByLabel("Service ID").fill(service!);
  await page.getByLabel("Method ID").fill(method!);
  await page.getByLabel("原始载荷").fill("");
  const rpcDone = page.waitForResponse((response) => response.request().method() === "POST" && response.url().endsWith(`/devices/${deviceId}/rpc/raw`));
  await page.getByRole("button", { name: "确认执行" }).click();
  const rpcResponse = await rpcDone;
  expect(rpcResponse.ok(), await rpcResponse.text()).toBeTruthy();
  const rpc = await rpcResponse.json();
  expect(rpc.operation.status).toBe("succeeded");
  expect(rpc.response_bytes).toBeGreaterThan(0);
  await expect(page.getByText("原始 RPC 已完成", { exact: true })).toBeVisible();

  const captured = page.waitForResponse((response) => response.request().method() === "POST" && response.url().includes(`/devices/${deviceId}/screenshot`));
  await page.getByRole("button", { name: "截图", exact: true }).click();
  const screenshot = await captured;
  expect(screenshot.ok()).toBeTruthy();
  expect(screenshot.headers()["content-type"]).toContain("image/png");
  const displayedImage = page.getByAltText("设备实时画面");
  await expect(displayedImage).toBeVisible();
  const signature = await displayedImage.evaluate(async (element: HTMLImageElement) => {
    const bytes = new Uint8Array(await (await fetch(element.src)).arrayBuffer());
    return Array.from(bytes.slice(0, 8));
  });
  expect(signature).toEqual([137, 80, 78, 71, 13, 10, 26, 10]);
  await expect.poll(() => displayedImage.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBeGreaterThan(0);

  let frames = 0;
  page.on("websocket", (socket) => {
    if (socket.url().endsWith(`/devices/${deviceId}/streams/screen`)) {
      socket.on("framereceived", ({ payload }) => { if (Buffer.isBuffer(payload)) frames++; });
    }
  });
  const inventory = await (await request.get(`${baseURL}/v2/devices`)).json();
  const hasData = inventory.devices.find((item: { device_id: string }) => item.device_id === deviceId)?.data_available;
  if (hasData) {
    await page.getByRole("button", { name: "启动镜像", exact: true }).click();
    try {
      await expect(page.getByText("镜像中", { exact: true })).toBeVisible();
      await expect.poll(() => frames, { timeout: 15_000 }).toBeGreaterThan(2);
      const mirroredShot = page.waitForResponse((response) => response.request().method() === "POST" && response.url().includes(`/devices/${deviceId}/screenshot`));
      await page.getByRole("button", { name: "截图", exact: true }).click();
      expect(JSON.parse((await mirroredShot).headers()["x-esp-iris-media"]).mirror_reused).toBe(1);
      await expect(page.getByText("镜像中", { exact: true })).toBeVisible();
    } finally {
      const stop = page.getByRole("button", { name: "停止镜像", exact: true });
      if (await stop.isVisible()) await stop.click();
    }
  } else {
    await expect(page.getByRole("button", { name: "启动镜像", exact: true })).toBeDisabled();
  }
  await page.getByRole("button", { name: "记录", exact: true }).click();
  await expect(page.getByRole("tab", { name: "设备操作" })).toBeVisible();
  const final = await (await request.get(`${baseURL}/v2/devices/${deviceId}`)).json();
  expect(final.boot_id_text).toBe(initial.boot_id_text);
  expect(final.device_id).toBe(deviceId);
  expect(errors).toEqual([]);
  await testInfo.attach("hardware-evidence", {
    body: JSON.stringify({ initial, final, rpc, screenshot: screenshot.headers(),
      pngSignature: signature, mirrorChunks: frames, errors }, null, 2),
    contentType: "application/json",
  });
});
