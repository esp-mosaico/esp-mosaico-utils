/*
 * SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
 * SPDX-License-Identifier: Apache-2.0
 */

#include "mosaico_boot_splash.h"

#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "esp_efuse.h"
#include "esp_efuse_table.h"
#include "esp_log.h"
#include "esp_rom_gpio.h"
#include "esp_rom_sys.h"
#include "hal/gpio_ll.h"
#include "hal/spi_hal.h"
#include "hal/spi_ll.h"
#include "sdkconfig.h"
#include "soc/gpio_sig_map.h"
#include "soc/spi_periph.h"

#define LCD_WIDTH 480U
#define LCD_HEIGHT 480U
#define LCD_POWER_GPIO 60
#define LCD_RESET_GPIO_V1_0 42
#define LCD_CLK_GPIO_V1_0 44
#define LCD_RESET_GPIO_V1_2 44
#define LCD_CLK_GPIO_V1_2 42
#define LCD_CS_GPIO 50
#define LCD_DATA0_GPIO 36
#define LCD_DATA1_GPIO 51
#define LCD_DATA2_GPIO 35
#define LCD_DATA3_GPIO 9
#define LCD_SPI_CLOCK_HZ 40000000U
#define LCD_SPI_SOURCE_HZ 40000000U
#define LCD_FIFO_BYTES 64U
#define LCD_CMD_WRITE 0x02U
#define LCD_COLOR_WRITE 0x32U
#define LCD_BOOT_BRIGHTNESS 0xFFU
#define LCD_TRANSFER_TIMEOUT_MS 100U

#define LOGO_CELL_PX 8U
#define LOGO_GLYPH_COLS 5U
#define LOGO_GLYPH_ROWS 7U
#define LOGO_CHAR_ADVANCE 6U
#define LOGO_CHAR_COUNT 7U
#define LOGO_WIDTH                                                             \
  (((LOGO_CHAR_COUNT - 1U) * LOGO_CHAR_ADVANCE + LOGO_GLYPH_COLS) *            \
   LOGO_CELL_PX)
#define LOGO_HEIGHT (LOGO_GLYPH_ROWS * LOGO_CELL_PX)
#define LOGO_X ((LCD_WIDTH - LOGO_WIDTH) / 2U)
#define LOGO_Y ((LCD_HEIGHT - LOGO_HEIGHT) / 2U)
#define LOGO_COLOR 0xFA60U

#define MOSAICO_HW_VERSION(major, minor)                                       \
  ((uint16_t)(((uint16_t)(major) << 8) | ((uint16_t)(minor) & 0xFFU)))

static const char *TAG = "boot_splash";
static spi_hal_context_t s_spi;
static spi_hal_dev_config_t s_spi_device;
static uint16_t s_hw_version;

/* Compact 5x7 lowercase "mosaico". Each set bit becomes one rounded 6x6 dot
 * in an 8x8 cell, matching the product wordmark without storing a bitmap. */
static const uint8_t s_logo[LOGO_CHAR_COUNT][LOGO_GLYPH_ROWS] = {
    {0x00, 0x1A, 0x15, 0x15, 0x15, 0x15, 0x15}, /* m */
    {0x00, 0x0E, 0x11, 0x11, 0x11, 0x11, 0x0E}, /* o */
    {0x00, 0x0F, 0x10, 0x0E, 0x01, 0x01, 0x1E}, /* s */
    {0x00, 0x0E, 0x01, 0x0F, 0x11, 0x13, 0x0D}, /* a */
    {0x04, 0x00, 0x0C, 0x04, 0x04, 0x04, 0x0E}, /* i */
    {0x00, 0x0F, 0x10, 0x10, 0x10, 0x10, 0x0F}, /* c */
    {0x00, 0x0E, 0x11, 0x11, 0x11, 0x11, 0x0E}, /* o */
};

static bool hardware_version_supported(void) {
  uint16_t version = 0;
  if (esp_efuse_read_field_blob(ESP_EFUSE_USER_DATA, &version,
                                sizeof(version) * 8U) != ESP_OK) {
    return false;
  }
  if (version != MOSAICO_HW_VERSION(1, 0) &&
      version != MOSAICO_HW_VERSION(1, 1) &&
      version != MOSAICO_HW_VERSION(1, 2)) {
    return false;
  }
  s_hw_version = version;
  return true;
}

static void gpio_output(int gpio, int level) {
  esp_rom_gpio_pad_select_gpio(gpio);
  gpio_ll_set_level(&GPIO, gpio, level);
  gpio_ll_output_enable(&GPIO, gpio);
}

static void route_spi_output(int gpio, int signal) {
  esp_rom_gpio_pad_select_gpio(gpio);
  esp_rom_gpio_connect_out_signal(gpio, signal, false, false);
  gpio_ll_output_enable(&GPIO, gpio);
}

static bool spi_wait(void) {
  const uint32_t started_ms = esp_log_early_timestamp();
  while (!spi_hal_usr_is_done(&s_spi)) {
    if ((uint32_t)(esp_log_early_timestamp() - started_ms) >=
        LCD_TRANSFER_TIMEOUT_MS) {
      return false;
    }
  }
  return true;
}

static bool spi_tx(const void *data, size_t size, uint8_t lines,
                   bool keep_cs_active) {
  const uint8_t *cursor = data;
  while (size > 0) {
    uint8_t fifo[LCD_FIFO_BYTES] = {0};
    const size_t chunk = size > sizeof(fifo) ? sizeof(fifo) : size;
    memcpy(fifo, cursor, chunk);
    const spi_hal_trans_config_t transaction = {
        .tx_bitlen = (int)(chunk * 8U),
        .send_buffer = fifo,
        .line_mode =
            {
                .cmd_lines = 1,
                .addr_lines = 1,
                .data_lines = lines,
            },
        .cs_keep_active = keep_cs_active || chunk < size,
    };
    spi_hal_setup_trans(&s_spi, &s_spi_device, &transaction);
    spi_hal_push_tx_buffer(&s_spi, &transaction);
    spi_hal_user_start(&s_spi);
    if (!spi_wait()) {
      return false;
    }
    cursor += chunk;
    size -= chunk;
  }
  return true;
}

static bool lcd_command(uint8_t command, const void *params,
                        size_t param_size) {
  uint8_t packet[16] = {LCD_CMD_WRITE, 0x00, command, 0x00};
  if (param_size > sizeof(packet) - 4U) {
    return false;
  }
  if (params != NULL && param_size > 0) {
    memcpy(&packet[4], params, param_size);
  }
  return spi_tx(packet, 4U + param_size, 1, false);
}

static bool lcd_set_window(uint16_t x, uint16_t y, uint16_t width,
                           uint16_t height) {
  const uint16_t x_end = x + width - 1U;
  const uint16_t y_end = y + height - 1U;
  const uint8_t columns[] = {
      (uint8_t)(x >> 8),
      (uint8_t)x,
      (uint8_t)(x_end >> 8),
      (uint8_t)x_end,
  };
  const uint8_t rows[] = {
      (uint8_t)(y >> 8),
      (uint8_t)y,
      (uint8_t)(y_end >> 8),
      (uint8_t)y_end,
  };
  return lcd_command(0x2A, columns, sizeof(columns)) &&
         lcd_command(0x2B, rows, sizeof(rows));
}

static void spi_init(void) {
  int __DECLARE_RCC_ATOMIC_ENV __attribute__((unused));
  spi_ll_enable_bus_clock(SPI2_HOST, true);
  spi_ll_reset_register(SPI2_HOST);
  spi_ll_enable_clock(SPI2_HOST, true);
  spi_ll_set_clk_source(&GPSPI2, SPI_CLK_SRC_XTAL);
  spi_ll_clk_source_pre_div(&GPSPI2, 1, 1);

  const int lcd_clk_gpio = s_hw_version == MOSAICO_HW_VERSION(1, 0)
                               ? LCD_CLK_GPIO_V1_0
                               : LCD_CLK_GPIO_V1_2;
  route_spi_output(lcd_clk_gpio, SPI2_CK_PAD_OUT_IDX);
  route_spi_output(LCD_DATA0_GPIO, SPI2_D_PAD_OUT_IDX);
  route_spi_output(LCD_DATA1_GPIO, SPI2_Q_PAD_OUT_IDX);
  route_spi_output(LCD_DATA2_GPIO, SPI2_WP_PAD_OUT_IDX);
  route_spi_output(LCD_DATA3_GPIO, SPI2_HOLD_PAD_OUT_IDX);
  route_spi_output(LCD_CS_GPIO, SPI2_CS_PAD_OUT_IDX);

  spi_hal_init(&s_spi, SPI2_HOST);
  s_spi_device = (spi_hal_dev_config_t){
      .mode = 0,
      .cs_pin_id = 0,
      .half_duplex = 1,
      .timing_conf =
          {
              .clock_source = SPI_CLK_SRC_XTAL,
              .source_pre_div = 1,
              .source_real_freq = LCD_SPI_SOURCE_HZ,
              .expect_freq = LCD_SPI_CLOCK_HZ,
              .real_freq = LCD_SPI_CLOCK_HZ,
          },
  };
  spi_ll_master_cal_clock(LCD_SPI_SOURCE_HZ, LCD_SPI_CLOCK_HZ, 128,
                          &s_spi_device.timing_conf.clock_reg);
  spi_hal_setup_device(&s_spi, &s_spi_device);
  spi_hal_enable_data_line(s_spi.hw, true, false);
}

static bool panel_init(void) {
  static const struct {
    uint8_t command;
    uint8_t data[4];
    uint8_t size;
  } init[] = {
      {0xFE, {0x20}, 1}, {0x19, {0x10}, 1},
      {0x1C, {0xA0}, 1}, {0xFE, {0x00}, 1},
      {0xC4, {0x80}, 1}, {0x3A, {0x55}, 1},
#if CONFIG_BSP_CO5300_ENABLE_TE
      {0x35, {0x00}, 1},
#endif
      {0x53, {0x20}, 1}, {0x51, {LCD_BOOT_BRIGHTNESS}, 1},
      {0x63, {0xFF}, 1}, {0x36, {0x00}, 1},
  };

  const int lcd_reset_gpio = s_hw_version == MOSAICO_HW_VERSION(1, 0)
                                 ? LCD_RESET_GPIO_V1_0
                                 : LCD_RESET_GPIO_V1_2;
  gpio_output(LCD_POWER_GPIO, 0);
  gpio_output(lcd_reset_gpio, 0);
  esp_rom_delay_us(10000);
  gpio_ll_set_level(&GPIO, lcd_reset_gpio, 1);
  esp_rom_delay_us(150000);

  spi_init();
  if (!lcd_command(0x11, NULL, 0)) {
    return false;
  }
  esp_rom_delay_us(60000);
  for (size_t i = 0; i < sizeof(init) / sizeof(init[0]); ++i) {
    if (!lcd_command(init[i].command, init[i].data, init[i].size)) {
      return false;
    }
  }
  return true;
}

static uint16_t logo_pixel(unsigned x, unsigned y) {
  if (x < LOGO_X || x >= LOGO_X + LOGO_WIDTH || y < LOGO_Y ||
      y >= LOGO_Y + LOGO_HEIGHT) {
    return 0;
  }

  const unsigned local_x = x - LOGO_X;
  const unsigned local_y = y - LOGO_Y;
  const unsigned cell_column = local_x / LOGO_CELL_PX;
  const unsigned character = cell_column / LOGO_CHAR_ADVANCE;
  const unsigned glyph_column = cell_column % LOGO_CHAR_ADVANCE;
  const unsigned glyph_row = local_y / LOGO_CELL_PX;
  if (character >= LOGO_CHAR_COUNT || glyph_column >= LOGO_GLYPH_COLS ||
      (s_logo[character][glyph_row] &
       (1U << (LOGO_GLYPH_COLS - 1U - glyph_column))) == 0U) {
    return 0;
  }

  const unsigned dot_x = local_x % LOGO_CELL_PX;
  const unsigned dot_y = local_y % LOGO_CELL_PX;
  if (dot_x < 1U || dot_x > 6U || dot_y < 1U || dot_y > 6U ||
      ((dot_x == 1U || dot_x == 6U) && (dot_y == 1U || dot_y == 6U))) {
    return 0;
  }
  return LOGO_COLOR;
}

static bool draw_splash(void) {
  if (!lcd_set_window(0, 0, LCD_WIDTH, LCD_HEIGHT)) {
    return false;
  }
  const uint8_t write_command[] = {LCD_COLOR_WRITE, 0x00, 0x2C, 0x00};
  if (!spi_tx(write_command, sizeof(write_command), 1, true)) {
    return false;
  }

  uint8_t fifo[LCD_FIFO_BYTES];
  size_t used = 0;
  for (unsigned y = 0; y < LCD_HEIGHT; ++y) {
    for (unsigned x = 0; x < LCD_WIDTH; ++x) {
      const uint16_t color = logo_pixel(x, y);
      fifo[used++] = (uint8_t)(color >> 8);
      fifo[used++] = (uint8_t)color;
      if (used == sizeof(fifo)) {
        const bool last = y == LCD_HEIGHT - 1U && x == LCD_WIDTH - 1U;
        if (!spi_tx(fifo, used, 4, !last)) {
          return false;
        }
        used = 0;
      }
    }
  }
  return used == 0U && lcd_command(0x29, NULL, 0);
}

bool mosaico_boot_splash_show(void) {
  if (!hardware_version_supported()) {
    ESP_LOGW(TAG, "unsupported hardware; LCD splash skipped");
    return false;
  }
  if (!panel_init() || !draw_splash()) {
    ESP_LOGW(TAG, "LCD splash failed; continuing boot");
    return false;
  }
  ESP_LOGW(TAG, "LCD boot splash visible");
  return true;
}
