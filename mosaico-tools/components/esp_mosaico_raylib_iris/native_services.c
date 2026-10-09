// SPDX-License-Identifier: Apache-2.0
#include "raylib_lite_native_services.h"
#include "esp_iris.h"
#include "iris_ota_support.h"
#include "iris_display_input.h"

static raylib_lite_result_t result(esp_err_t err)
{
    return err == ESP_OK ? RAYLIB_LITE_OK : RAYLIB_LITE_PLATFORM_ERROR;
}
static raylib_lite_result_t boot(void)
{
    esp_err_t err = esp_iris_boot_probe();
    if (err != ESP_OK) return result(err);
    iris_ota_support_start();
    return RAYLIB_LITE_OK;
}
static raylib_lite_result_t attach(raylib_lite_video_backend_t video,
                                    raylib_lite_input_queue_t *input)
{
    raylib_lite_video_info_t info;
    if (!video.get_info) return RAYLIB_LITE_INVALID_ARGUMENT;
    raylib_lite_result_t err = video.get_info(video.context, &info);
    if (err != RAYLIB_LITE_OK) return err;
    return result(mosaico_iris_display_input_register(video, input,
                                                     info.width, info.height));
}
static raylib_lite_result_t first_present(void)
{
    return result(esp_iris_mark_healthy());
}
static raylib_lite_result_t detach(void)
{
    return result(mosaico_iris_display_input_unregister());
}
const raylib_lite_native_services_t *raylib_lite_native_services_get(void)
{
    static const raylib_lite_native_services_t services = {
        .boot = boot, .attach = attach,
        .first_present = first_present, .detach = detach,
    };
    return &services;
}
