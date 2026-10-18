// SPDX-License-Identifier: Apache-2.0
/* Own the ESP32-S31 regulator and digital-system reset boundary. This is the
 * supply/reset implementation exercised by the controlled IDF188 Recovery
 * handover experiment. Older retained bootloaders can leave DREG at code10;
 * CPU-only restarts can leave PVT and DMA active. Raise both DREG values to12
 * in SDK order, release PVT before a digital-system restart, and retain the
 * RTC watchdog as the bounded fallback. See docs/validation-0.2.1.md. */
#include <stdint.h>
#include <stdbool.h>

#include "sdkconfig.h"
#include "soc/soc_caps.h"

#if CONFIG_IDF_TARGET_ESP32S31

#if !SOC_PMU_PVT_SUPPORTED
#error "The ESP32-S31 needs an ESP-IDF with PVT auto dbias (38fea2d7 or later)"
#endif

#include "esp_attr.h"
#include "esp_cpu.h"
#include "esp_log.h"
#include "esp_macros.h"
#include "esp_memory_utils.h"
#include "esp_rom_sys.h"
#include "esp_system.h"
#include "esp_private/regi2c_ctrl.h"
#include "esp_private/rtc_clk.h"
#include "esp_private/startup_internal.h"
#include "esp_private/system_internal.h"
#include "esp32s31/rom/cache.h"
#include "esp32s31/rom/ets_sys.h"
#include "hal/efuse_hal.h"
#include "hal/wdt_hal.h"
#include "riscv/rv_utils.h"
#include "soc/hp_sys_clkrst_reg.h"
#include "soc/hp_system_reg.h"
#include "soc/pmu_reg.h"
#include "soc/pvt_reg.h"
#include "soc/regi2c_bias.h"
#include "soc/rtc.h"

extern int _bss_end;

static const char *TAG = "board_supply";

#define DREG_1P1_CODE 12

/* pmu_pvt.c's pvt_func_enable(true) takes the regulator from the PMU by
 * clearing this select bit; handing it back sets it again. The PMU is in the
 * LP domain and keeps whatever it was told across any reset but a power-on
 * one, so the bit is safe to read in any state, the restart path included. */
static IRAM_ATTR bool pvt_holds_regulator(void)
{
    return !REG_GET_BIT(PMU_HP_ACTIVE_HP_REGULATOR0_REG, PMU_DIG_REGULATOR0_DBIAS_SEL);
}

/* pmu_pvt.c: charge_pump_enable(false) and pvt_func_enable(false), register
 * writes only: the restart path runs with the other core stalled and may run
 * with the cache off, so ESP-IDF's pvt_auto_dbias_enable(false), which also
 * releases the BBPLL through the clock tree, is not safe there. The PMU takes
 * the regulator back at the PVT's dbias. */
static IRAM_ATTR void pvt_release(void)
{
    CLEAR_PERI_REG_MASK(PVT_PMUP_DRV_CFG_REG, PVT_PUMP_EN);
    const uint32_t hp = REG_GET_FIELD(PMU_HP_ACTIVE_HP_REGULATOR0_REG, PMU_HP_DBIAS_VOL);
    const uint32_t lp = REG_GET_FIELD(PMU_HP_ACTIVE_HP_REGULATOR0_REG, PMU_LP_DBIAS_VOL);
    SET_PERI_REG_BITS(PMU_HP_ACTIVE_HP_REGULATOR0_REG, PMU_HP_ACTIVE_HP_REGULATOR_DBIAS, hp,
                      PMU_HP_ACTIVE_HP_REGULATOR_DBIAS_S);
    SET_PERI_REG_BITS(PMU_HP_SLEEP_LP_REGULATOR0_REG, PMU_HP_SLEEP_LP_REGULATOR_DBIAS, lp,
                      PMU_HP_SLEEP_LP_REGULATOR_DBIAS_S);
    CLEAR_PERI_REG_MASK(PVT_DBIAS_TIMER_REG, PVT_TIMER_EN);
    SET_PERI_REG_MASK(PMU_HP_ACTIVE_HP_REGULATOR0_REG, PMU_DIG_REGULATOR0_DBIAS_SEL);
    CLEAR_PERI_REG_MASK(HP_SYS_CLKRST_PVT0_CTRL0_REG, HP_SYS_CLKRST_REG_PVT0_CLK_EN);
}

/* How far this boot's start-up and restart got, kept in LP memory for the
 * next boot's report: a stall there ends in an RTC watchdog reset with no
 * log and no core dump. Volatile: each stage is overwritten by the next with
 * only register accesses in between, so the compiler would drop the earlier
 * stores and a stall would read as an earlier stage. */
typedef struct {
    uint32_t magic;
    uint8_t init, restart;             /* this boot */
    uint8_t prev_init, prev_restart;   /* the boot before it */
} supply_trace_t;
#define TRACE_MAGIC 0x53555031u        /* "SUP1" */
#define INIT_DONE 5
#define RESTART_RESET 3
static RTC_NOINIT_ATTR volatile supply_trace_t s_trace;

void mosaico_supply_include(void) {}

int mosaico_supply_dbias(void)
{
    return pvt_holds_regulator() ? (int)REG_GET_FIELD(PMU_HP_ACTIVE_HP_REGULATOR0_REG, PMU_HP_DBIAS_VOL) : -1;
}

void mosaico_supply_report(void)
{
    const bool clean = s_trace.prev_init == INIT_DONE &&
                       (s_trace.prev_restart == 0 || s_trace.prev_restart == RESTART_RESET);
    ESP_LOG_LEVEL(clean ? ESP_LOG_INFO : ESP_LOG_WARN, TAG,
                  "dbias=%d; previous boot: start-up stage %u/%u, restart stage %u/%u; reset reason %d",
                  mosaico_supply_dbias(), s_trace.prev_init, INIT_DONE, s_trace.prev_restart,
                  RESTART_RESET, (int)esp_reset_reason());
}

/* ESP-IDF's ESP32-S31 esp_restart_noos() and esp_restart_noos_inner(), except
 * that the last step is a digital system reset (esp_restart_noos_dig()'s)
 * instead of a CPU reset. */
static void IRAM_ATTR __attribute__((noinline, noreturn)) restart_system(void)
{
    const uint32_t core_id = esp_cpu_get_core_id();
#if CONFIG_SPIRAM
    Cache_WriteBack_All(CACHE_MAP_L1_DCACHE);
#endif
    esp_system_reset_modules_on_exit();
    rtc_clk_cpu_set_to_default_config();
    ets_set_appcpu_boot_addr(0);
#if CONFIG_SPIRAM_INSTRUCTIONS_RODATA
    REG_CLR_BIT(HP_SYS_HP_PSRAM_FLASH_ADDR_INTERCHANGE_REG,
                HP_SYS_HP_PSRAM_FLASH_ADDR_INTERCHANGE_DMA | HP_SYS_HP_PSRAM_FLASH_ADDR_INTERCHANGE_CPU);
#endif
    /* The stall state lives outside the digital domain. */
    esp_cpu_unstall(core_id == 0 ? 1 : 0);
    s_trace.restart = RESTART_RESET;
    esp_rom_software_reset_system();
    ESP_INFINITE_LOOP();
}

/* Every restart path ends here: esp_restart(), a start-up failure and the
 * panic handler, which may run with the cache off. */
void __real_esp_restart_noos(void) __attribute__((noreturn));
void IRAM_ATTR __attribute__((noreturn)) __wrap_esp_restart_noos(void)
{
    if (!pvt_holds_regulator()) __real_esp_restart_noos();
    rv_utils_intr_global_disable();
    s_trace.restart = 1;
    pvt_release();
    s_trace.restart = 2;

    /* The RTC watchdog as ESP-IDF arms it: a system reset after 1 s if the
     * reset or the boot after it gets stuck. */
    wdt_hal_context_t rtc_wdt = {0};
    wdt_hal_init(&rtc_wdt, WDT_RWDT, 0, false);
    const uint32_t ticks = (uint32_t)rtc_clk_slow_freq_get_hz();
    wdt_hal_write_protect_disable(&rtc_wdt);
    wdt_hal_config_stage(&rtc_wdt, WDT_STAGE0, ticks, WDT_STAGE_ACTION_RESET_SYSTEM);
    wdt_hal_config_stage(&rtc_wdt, WDT_STAGE1, ticks, WDT_STAGE_ACTION_RESET_RTC);
    wdt_hal_set_flashboot_en(&rtc_wdt, true);
    wdt_hal_write_protect_enable(&rtc_wdt);

    const uint32_t other = esp_cpu_get_core_id() == 0 ? 1 : 0;
    esp_cpu_reset(other);
    esp_cpu_stall(other);
    if (esp_ptr_external_ram(esp_cpu_get_sp())) {
        rv_utils_set_sp((void *)ESP_ALIGN_DOWN((uint32_t)&_bss_end, 16));
    }
    restart_system();
}

ESP_SYSTEM_INIT_FN(mosaico_supply_init, SECONDARY, BIT(0), 100)
{
    const bool traced = s_trace.magic == TRACE_MAGIC;
    s_trace = (supply_trace_t){
        .magic = TRACE_MAGIC,
        .init = 1,
        .prev_init = traced ? s_trace.init : 0,
        .prev_restart = traced ? s_trace.restart : 0,
    };

    /* pmu_init() started the PVT on a chip with its calibration eFuses
     * (block version 1 or later); without them the dbias stays fixed. */
    const bool pvt = pvt_holds_regulator();
    REGI2C_CLOCK_ENABLE();
    const uint32_t dreg = REGI2C_READ_MASK(I2C_BIAS, I2C_BIAS_DREG_1P1);
    const uint32_t dreg_pvt = REGI2C_READ_MASK(I2C_BIAS, I2C_BIAS_DREG_1P1_PVT);
    REGI2C_CLOCK_DISABLE();
    s_trace.init = 2;
    if (dreg < DREG_1P1_CODE || dreg_pvt < DREG_1P1_CODE) {
#if CONFIG_ESP_ENABLE_PVT
        if (pvt) pvt_auto_dbias_enable(false);
#endif
        s_trace.init = 3;
        REGI2C_CLOCK_ENABLE();
        if (dreg < DREG_1P1_CODE) REGI2C_WRITE_MASK(I2C_BIAS, I2C_BIAS_DREG_1P1, DREG_1P1_CODE);
        if (dreg_pvt < DREG_1P1_CODE) REGI2C_WRITE_MASK(I2C_BIAS, I2C_BIAS_DREG_1P1_PVT, DREG_1P1_CODE);
        REGI2C_CLOCK_DISABLE();
        s_trace.init = 4;
#if CONFIG_ESP_ENABLE_PVT
        if (pvt) {
            pvt_auto_dbias_enable(true);
            esp_rom_delay_us(1000);   /* as pmu_init() waits after starting it */
        }
#endif
    }
    s_trace.init = INIT_DONE;
    ESP_LOGI(TAG, "dreg_1p1 %lu/%lu -> %u, dbias %s %d (eFuse block v%lu)",
             (unsigned long)dreg, (unsigned long)dreg_pvt, DREG_1P1_CODE, pvt ? "pvt" : "fixed",
             pvt ? mosaico_supply_dbias()
                 : (int)REG_GET_FIELD(PMU_HP_ACTIVE_HP_REGULATOR0_REG, PMU_HP_ACTIVE_HP_REGULATOR_DBIAS),
             (unsigned long)efuse_hal_blk_version());
    return ESP_OK;
}

#else

#include "esp_attr.h"

void mosaico_supply_include(void) {}

int mosaico_supply_dbias(void) { return -1; }

void mosaico_supply_report(void) {}

void __real_esp_restart_noos(void) __attribute__((noreturn));
void IRAM_ATTR __attribute__((noreturn)) __wrap_esp_restart_noos(void) { __real_esp_restart_noos(); }

#endif
