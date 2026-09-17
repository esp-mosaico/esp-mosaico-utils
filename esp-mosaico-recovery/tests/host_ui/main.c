/* Run the production LVGL pages with deterministic network/service responses. */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include UI_SOURCE
#include UI_INPUT_SOURCE

static factory_network_snapshot_t network;
static esp_err_t network_result = ESP_OK;
static esp_err_t connect_result = ESP_OK;
static unsigned bridge_opens;
static bool bridge_running;
static bool usb_session = true;
static esp_iris_rpc_handler_t input_handler;

esp_err_t esp_iris_rpc_register(uint16_t service, uint16_t method,
                                esp_iris_rpc_handler_t handler, void *context)
{
    assert(service == 0x1001 && method == 1 && context == NULL);
    input_handler = handler;
    return ESP_OK;
}

esp_err_t factory_network_get_snapshot(factory_network_snapshot_t *out)
{ *out = network; return network_result; }
esp_err_t factory_network_request_scan(void) { return ESP_OK; }
esp_err_t factory_network_forget(void) { memset(&network, 0, sizeof(network)); return ESP_OK; }
esp_err_t factory_network_connect(const char *ssid, const char *password)
{
    (void)password;
    if (connect_result == ESP_OK) {
        network.state = FACTORY_NETWORK_CONNECTING;
        strlcpy(network.ssid, ssid, sizeof(network.ssid));
    }
    return connect_result;
}
esp_err_t factory_bridge_open(void) { bridge_opens++; bridge_running = true; return ESP_OK; }
void iris_bridge_stop(void) { bridge_running = false; }
bool iris_bridge_is_running(void) { return bridge_running; }
void iris_bridge_get_snapshot(iris_bridge_snapshot_t *out)
{
    memset(out, 0, sizeof(*out));
    out->running = bridge_running;
    strcpy(out->server_url, "https://transport.example.invalid");
    strcpy(out->state, "WAITING_PAIRING");
    strcpy(out->code, "1234567890");
    out->expires_in_ms = 120000;
}
esp_err_t esp_iris_pairing_token_get(char out[65]) { strcpy(out, "123456"); return ESP_OK; }
esp_err_t esp_iris_get_status(esp_iris_status_t *out)
{
    memset(out, 0, sizeof(*out));
    out->session_ready = true;
    out->transport = usb_session ? ESP_IRIS_TRANSPORT_KIND_USB : ESP_IRIS_TRANSPORT_KIND_TCP;
    return ESP_OK;
}
esp_err_t esp_iris_ota_get_status(esp_iris_ota_status_t *out) { memset(out, 0, sizeof(*out)); return ESP_OK; }
esp_err_t factory_nand_update_request_scan(void) { return ESP_OK; }
esp_err_t factory_nand_update_get_snapshot(factory_nand_update_snapshot_t *out)
{ memset(out, 0, sizeof(*out)); return ESP_OK; }
esp_err_t factory_system_update_start_nand(const char *path) { (void)path; return ESP_OK; }
esp_err_t factory_system_update_get_status(factory_system_update_status_t *out)
{ memset(out, 0, sizeof(*out)); return ESP_OK; }

static lv_obj_t *button(lv_obj_t *screen, const char *text)
{
    for (unsigned i = 0; i < lv_obj_get_child_count(screen); i++) {
        lv_obj_t *obj = lv_obj_get_child(screen, i);
        if (!lv_obj_check_type(obj, &lv_button_class)) continue;
        lv_obj_t *label = lv_obj_get_child(obj, 0);
        if (label && lv_obj_check_type(label, &lv_label_class) &&
            strcmp(lv_label_get_text(label), text) == 0) return obj;
    }
    assert(!"Button not found");
    return NULL;
}

static void click(lv_obj_t *screen, const char *text)
{
    lv_obj_update_layout(screen);
    lv_area_t area;
    lv_obj_get_coords(button(screen, text), &area);
    const uint16_t x = (area.x1 + area.x2) / 2;
    const uint16_t y = (area.y1 + area.y2) / 2;
    uint8_t message[12] = {0, 0, x & 255, x >> 8, y & 255, y >> 8};
    uint8_t response[12];
    size_t size;
    esp_iris_rpc_request_t request = {.payload = message, .payload_size = sizeof(message)};
    for (unsigned phase = 0; phase <= 2; phase += 2) {
        message[0] = phase;
        lv_tick_inc(30);
        assert(input_handler(&request, response, sizeof(response), &size, NULL) == ESP_OK);
        assert(size == sizeof(message) && memcmp(response, message, size) == 0);
    }
}

static void check_button_bounds(lv_obj_t *parent)
{
    for (unsigned i = 0; i < lv_obj_get_child_count(parent); i++) {
        lv_obj_t *obj = lv_obj_get_child(parent, i);
        if (lv_obj_check_type(obj, &lv_button_class)) {
            lv_obj_t *label = lv_obj_get_child(obj, 0);
            if (label && lv_obj_check_type(label, &lv_label_class)) {
                lv_area_t outer, inner;
                lv_obj_get_content_coords(obj, &outer);
                lv_obj_get_coords(label, &inner);
                if (inner.x1 < outer.x1 || inner.y1 < outer.y1 ||
                    inner.x2 > outer.x2 || inner.y2 > outer.y2) {
                    fprintf(stderr, "Button text outside content: %s\n", lv_label_get_text(label));
                    abort();
                }
            }
        }
        check_button_bounds(obj);
    }
}

static void capture(lv_obj_t *screen, const char *name)
{
    const char *dir = getenv("RECOVERY_UI_CAPTURE_DIR");
    if (!dir) return;
    lv_screen_load(screen);
    lv_obj_update_layout(screen);
    lv_draw_buf_t *buf = lv_snapshot_take(screen, LV_COLOR_FORMAT_RGB888);
    assert(buf);
    char path[1024];
    snprintf(path, sizeof(path), "%s/%s.ppm", dir, name);
    FILE *file = fopen(path, "wb");
    assert(file);
    fprintf(file, "P6\n%u %u\n255\n", buf->header.w, buf->header.h);
    for (unsigned y = 0; y < buf->header.h; y++) {
        for (unsigned x = 0; x < buf->header.w; x++) {
            const uint8_t *pixel = buf->data + y * buf->header.stride + x * 3;
            const uint8_t rgb[] = {pixel[2], pixel[1], pixel[0]};
            assert(fwrite(rgb, 1, 3, file) == 3);
        }
    }
    fclose(file);
    lv_draw_buf_destroy(buf);
}

int main(void)
{
    lv_init();
    lv_display_create(480, 480);
    assert(factory_ui_start() == ESP_OK);
    assert(factory_ui_input_register() == ESP_OK);
    uint8_t bad_point[12] = {0, 0, 0xff, 0xff};
    uint8_t reply[12];
    size_t reply_size = 0;
    esp_iris_rpc_request_t request = {.payload = bad_point, .payload_size = sizeof(bad_point)};
    assert(input_handler(&request, reply, sizeof(reply), &reply_size, NULL) == ESP_ERR_INVALID_ARG);
    request.payload_size = 1;
    assert(input_handler(&request, reply, sizeof(reply), &reply_size, NULL) == ESP_ERR_INVALID_SIZE);
    usb_session = false;
    assert(input_handler(&request, reply, sizeof(reply), &reply_size, NULL) == ESP_ERR_NOT_ALLOWED);
    usb_session = true;
    lv_obj_t *screens[] = {s_ui.ready_screen, s_ui.wifi_screen, s_ui.pairing_screen,
        s_ui.bridge_screen, s_ui.nand_list_screen, s_ui.nand_confirm_screen, s_ui.result_screen};
    for (unsigned i = 0; i < sizeof(screens) / sizeof(screens[0]); i++) {
        lv_obj_update_layout(screens[i]);
        check_button_bounds(screens[i]);
    }
    esp_iris_status_t iris = {0};
    link_status_update(&network, &iris);
    capture(s_ui.ready_screen, "recovery-home");

    /* No credentials: configure first, and do not start a Bridge worker. */
    click(s_ui.ready_screen, "Download From Spark");
    assert(s_ui.page == FACTORY_PAGE_WIFI && bridge_opens == 0);
    assert(s_ui.spark_download_pending);
    capture(s_ui.wifi_screen, "spark-wifi");
    strcpy(s_ui.selected_ssid, "Test network");
    show_page(FACTORY_PAGE_PASSWORD);
    lv_textarea_set_text(s_ui.password_input, "test-password");
    connect_result = ESP_FAIL;
    password_submit();
    assert(s_ui.page == FACTORY_PAGE_PASSWORD && s_ui.spark_download_pending);
    connect_result = ESP_OK;
    password_submit();
    assert(s_ui.page == FACTORY_PAGE_WIFI);
    network_ui_update(&network);
    assert(bridge_opens == 0);
    network.state = FACTORY_NETWORK_FAILED;
    network_ui_update(&network);
    assert(s_ui.page == FACTORY_PAGE_WIFI && bridge_opens == 0);
    network.state = FACTORY_NETWORK_CONNECTED;
    network_ui_update(&network); /* A connected event without IP is insufficient. */
    assert(bridge_opens == 0);
    strcpy(network.ip, "192.0.2.10");
    network_ui_update(&network);
    assert(s_ui.page == FACTORY_PAGE_BRIDGE && bridge_opens == 1);
    assert(!s_ui.spark_download_pending);
    network_ui_update(&network);
    assert(bridge_opens == 1);
    assert(strcmp(lv_label_get_text(s_ui.bridge_endpoint), SPARK_WEBSITE) == 0);
    capture(s_ui.bridge_screen, "spark-download");

    /* Back cancels continuation, even if connection finishes later. */
    show_page(FACTORY_PAGE_READY);
    memset(&network, 0, sizeof(network));
    click(s_ui.ready_screen, "Download From Spark");
    click(s_ui.wifi_screen, LV_SYMBOL_LEFT);
    network.state = FACTORY_NETWORK_CONNECTED;
    strcpy(network.ip, "192.0.2.10");
    network_ui_update(&network);
    assert(s_ui.page == FACTORY_PAGE_READY && bridge_opens == 1);

    /* Ordinary Wi-Fi setup does not opt into Spark. */
    click(s_ui.ready_screen, "Wi-Fi");
    show_page(FACTORY_PAGE_PASSWORD);
    password_submit();
    assert(s_ui.page == FACTORY_PAGE_READY && !s_ui.spark_download_pending);
    network.state = FACTORY_NETWORK_CONNECTED;
    network_ui_update(&network);
    assert(bridge_opens == 1);

    /* Existing configuration can use the worker's reconnect/wait behavior. */
    network.credentials_saved = true;
    network.state = FACTORY_NETWORK_CONNECTING;
    click(s_ui.ready_screen, "Download From Spark");
    assert(s_ui.page == FACTORY_PAGE_BRIDGE && bridge_opens == 2);
    click(s_ui.bridge_screen, "Cancel");
    assert(s_ui.page == FACTORY_PAGE_READY && !bridge_running);

    /* Missing network state fails into setup; other operations cancel it. */
    network_result = ESP_FAIL;
    click(s_ui.ready_screen, "Download From Spark");
    assert(s_ui.page == FACTORY_PAGE_WIFI && bridge_opens == 2);
    show_page(FACTORY_PAGE_UPDATE);
    network.state = FACTORY_NETWORK_CONNECTED;
    network_ui_update(&network);
    assert(s_ui.page == FACTORY_PAGE_UPDATE && bridge_opens == 2);
    show_page(FACTORY_PAGE_READY);
    click(s_ui.ready_screen, "NAND update");
    assert(s_ui.page == FACTORY_PAGE_NAND_LIST);
    puts("Recovery UI layout and Spark/Wi-Fi flow checks passed");
    lv_deinit();
    return 0;
}
