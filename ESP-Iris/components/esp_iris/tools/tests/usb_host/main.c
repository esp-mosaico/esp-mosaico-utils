#include "sdk.h"
#include USB_SOURCE

int main(void)
{
    iris_runtime_t control = {0}, data = {.data_link = true};
    iris_transport_state_t c = {0}, d = {0};
    fail_install = true;
    assert(usb_start(&control, &c) == ESP_FAIL);
    assert(!registrations && !shutdown_handler && !c.driver_started);
    fail_install = false;
    fail_register = true;
    assert(usb_start(&control, &c) == ESP_FAIL);
    assert(uninstalls == 1 && !s_users && !shutdown_handler);
    fail_register = false;
    fail_cdc = true;
    assert(usb_start(&control, &c) == ESP_FAIL);
    assert(uninstalls == 2 && removals == 1 && !shutdown_handler);
    fail_cdc = false;
    assert(usb_start(&control, &c) == ESP_OK);
    unsigned installed = installs, registered = registrations;
    fail_cdc = true;
    assert(usb_start(&data, &d) == ESP_FAIL);
    assert(installs == installed && registrations == registered && shutdown_handler);
    fail_cdc = false;
    assert(usb_start(&data, &d) == ESP_OK);
    assert(installs == installed && registrations == registered && s_users == 2);
    usb_stop(&control, &c);
    assert(s_users == 1 && shutdown_handler && uninstalls == 2);
    usb_stop(&data, &d);
    assert(!s_users && !shutdown_handler && uninstalls == 3 && removals == 2);

    assert(usb_start(&control, &c) == ESP_OK);
    c.link_up = true;
    shutdown_handler();
    assert(stop_step == 3 && !clock_enabled);
    uint8_t byte = 0;
    assert(usb_read(&control, &c, &byte, 1) == -ENOTCONN);
    assert(usb_write(&control, &c, &byte, 1) == -ENOTCONN);
    assert(usb_poll(&control, &c) == IRIS_LINK_EVENT_NONE && io_calls == 0);
    shutdown_handler(); /* Idempotent; do not touch the stopped controller. */
    usb_stop(&control, &c); /* No queue teardown against unclocked hardware. */
    assert(stop_step == 3 && uninstalls == 3);
    return 0;
}
