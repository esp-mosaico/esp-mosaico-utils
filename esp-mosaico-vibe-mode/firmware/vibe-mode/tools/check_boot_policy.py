#!/usr/bin/env python3
"""Compile the single-slot selector with pinned IDF OTA code and a faulting flash model.

This is a host-only check. It neither builds firmware nor accesses a device.
SDK functions are read from the supplied exact checkout instead of copied here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest

IDF_COMMIT = "188e3e55bb20505b5fa9dc49ee390bf42c58b4ee"
PROJECT: Path
IDF: Path


def function(source: str, name: str) -> str:
    match = re.search(r"(?m)^(?:static )?[\w *]+\b" + re.escape(name) +
                      r"\([^;]*?\)\s*\{", source)
    if match is None:
        raise ValueError("Missing actual source function: " + name)
    # The pinned SDK has alternative #if branches opening the same block.
    # Its function closing braces are unindented; inner blocks are indented.
    end = re.search(r"(?m)^}", source[match.end():])
    if end is None:
        raise ValueError("Unclosed function: " + name)
    return source[match.start():match.end() + end.end()]


PREAMBLE = r'''
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <setjmp.h>
#include <inttypes.h>
#define CONFIG_BOOTLOADER_APP_ROLLBACK 1
#define ESP_OK 0
#define ESP_FAIL -1
#define ESP_ERR_INVALID_ARG -2
#define ESP_ERR_NOT_FOUND -3
#define ESP_ERR_NOT_SUPPORTED -4
#define ESP_ERR_OTA_ROLLBACK_FAILED -5
#define FACTORY_INDEX -1
#define INVALID_INDEX -99
#define TEST_APP_INDEX -2
#define MAX_OTA_SLOTS 16
#define FLASH_SECTOR_SIZE 4096U
#include "mosaico_recovery_contract.h"
#define CONFIG_FACTORY_RECOVERY_BOOT_GPIO 0
#define ESP_LOGD(...) ((void)0)
#define ESP_LOGI(...) ((void)0)
#define ESP_LOGW(...) ((void)0)
#define ESP_LOGE(...) ((void)0)
#define MAX(a,b) ((a) > (b) ? (a) : (b))
#define MIN(a,b) ((a) < (b) ? (a) : (b))
#define OTA_SLOT(subtype) ((subtype) & 0x0fU)
#define ESP_PARTITION_SUBTYPE_APP_OTA_MIN 0x10
typedef int esp_err_t;
typedef uint32_t esp_partition_subtype_t;
typedef struct { uint32_t offset, size; } esp_partition_pos_t;
typedef struct {
    esp_partition_pos_t factory, test, ota[MAX_OTA_SLOTS], ota_info;
    uint32_t app_count;
} bootloader_state_t;
typedef struct { uint32_t address, size, erase_size; int subtype; } esp_partition_t;
static uint8_t flash_bytes[8192];
static bootloader_state_t model_layout;
static uint32_t normal_capacity;
static const esp_partition_t data_partition = {0x9000, 8192, 4096, 0};
static unsigned reads, erases, writes, native_calls, fail_read, fail_erase,
    fail_write, partial_erase, corrupt_write, cut_erase, cut_write;
static bool erase_failure_after_mutation, table_ok, maintenance;
static bool fail_post_native_read, post_native;
static bool ota_has_initial_contents;
static bool flash_encrypted, secure_boot;
static jmp_buf power_cut, loader_exit;
typedef struct { uint32_t address; } esp_image_metadata_t;
static unsigned normal_load_attempts, recovery_load_attempts;
static uint32_t loaded_address;
static bool normal_image_valid, recovery_image_valid;
#ifndef bzero
#define bzero(address, length) memset(address, 0, length)
#endif
static bool check_anti_rollback(const esp_partition_pos_t *p) { (void)p; return true; }
static bool try_load_partition(const esp_partition_pos_t *p, esp_image_metadata_t *data)
{
    data->address = p->offset;
    if (p->offset == MOSAICO_APPLICATION_ADDRESS) { ++normal_load_attempts; return normal_image_valid; }
    if (p->offset == MOSAICO_RECOVERY_ADDRESS) { ++recovery_load_attempts; return recovery_image_valid; }
    abort();
}
static esp_partition_pos_t index_to_partition(const bootloader_state_t *bs, int i)
{ return i == FACTORY_INDEX ? bs->factory : bs->ota[i]; }
static void set_actual_ota_seq(const bootloader_state_t *bs, int i) { (void)bs; (void)i; }
static void log_invalid_app_partition(int i) { (void)i; }
static void load_image(const esp_image_metadata_t *data)
{ loaded_address = data->address; longjmp(loader_exit, 1); }
static void bootloader_reset(void) { longjmp(loader_exit, 2); }
static int native_override;
static int bootloader_common_select_otadata(const esp_ota_select_entry_t *, bool *, bool);
static int bootloader_utility_get_selected_boot_partition(const bootloader_state_t *);
static int selected_boot_partition(const bootloader_state_t *);

static uint32_t esp_rom_crc32_le(uint32_t initial, const uint8_t *bytes, size_t len)
{
    uint32_t crc = ~initial;
    for (size_t i = 0; i < len; ++i) {
        crc ^= bytes[i];
        for (unsigned bit = 0; bit < 8; ++bit)
            crc = (crc >> 1) ^ (0xedb88320U & (0U - (crc & 1U)));
    }
    return ~crc;
}
static int bootloader_flash_read(uint32_t offset, void *out, size_t len, bool decrypt)
{
    (void)decrypt;
    if (++reads == fail_read) return ESP_FAIL;
    if (post_native && fail_post_native_read) return ESP_FAIL;
    if (offset < 0x9000 || len > sizeof(flash_bytes) || offset - 0x9000 > sizeof(flash_bytes) - len)
        abort();
    memcpy(out, flash_bytes + offset - 0x9000, len);
    return ESP_OK;
}
static int bootloader_flash_erase_sector(uint32_t sector)
{
    if (sector != 9 && sector != 10) abort();
    ++erases;
    if (erases == fail_erase && !erase_failure_after_mutation) return ESP_FAIL;
    memset(flash_bytes + (sector - 9) * 4096, 0xff, 4096);
    if (erases == partial_erase) flash_bytes[(sector - 9) * 4096 + 4095] = 0;
    if (erases == cut_erase) longjmp(power_cut, 1);
    if (erases == fail_erase) return ESP_FAIL;
    return ESP_OK;
}
static int bootloader_flash_write(uint32_t offset, const void *data, size_t len, bool encrypted)
{
    (void)encrypted;
    if (offset < 0x9000 || offset + len > 0xb000) abort();
    ++writes;
    if (writes == fail_write) return ESP_FAIL;
    memcpy(flash_bytes + offset - 0x9000, data, len);
    if (writes == corrupt_write) flash_bytes[offset - 0x9000 + len - 1] ^= 1;
    if (writes == cut_write) longjmp(power_cut, 1);
    return ESP_OK;
}
static int bootloader_common_read_otadata(const esp_partition_pos_t *pos, esp_ota_select_entry_t entries[2])
{
    if (bootloader_flash_read(pos->offset, &entries[0], sizeof(entries[0]), true) != ESP_OK)
        return ESP_FAIL;
    return bootloader_flash_read(pos->offset + 4096, &entries[1], sizeof(entries[1]), true);
}
static bool esp_efuse_is_flash_encryption_enabled(void) { return flash_encrypted; }
static bool esp_secure_boot_enabled(void) { return secure_boot; }
static bool bootloader_utility_load_partition_table(bootloader_state_t *bs)
{ *bs = model_layout; return table_ok; }
static bool factory_recovery_requested(void) { return maintenance; }
static bool bootstrap_recovery_requested(const bootloader_state_t *bs) { (void)bs; return false; }
static bool software_recovery_requested(void) { return maintenance; }
static bool is_ota_partition(const esp_partition_t *p) { return p->subtype >= 0x10 && p->subtype < 0x20; }
static uint8_t esp_ota_get_app_partition_count(void) { return model_layout.app_count; }
static const esp_partition_t *read_otadata(esp_ota_select_entry_t entries[2])
{ return bootloader_common_read_otadata(&model_layout.ota_info, entries) == ESP_OK ? &data_partition : NULL; }
static int esp_partition_erase_range(const esp_partition_t *p, uint32_t offset, uint32_t len)
{ if (len != 4096) abort(); return bootloader_flash_erase_sector((p->address + offset) / 4096); }
static int esp_partition_write(const esp_partition_t *p, uint32_t offset, const void *data, size_t len)
{ return bootloader_flash_write(p->address + offset, data, len, false); }
static bool esp_ota_check_rollback_is_possible(void) { return false; }
'''

MODEL = r'''
static int bootloader_utility_get_selected_boot_partition(const bootloader_state_t *bs)
{
    ++native_calls;
    if (native_override) return native_override;
    const int result = idf188_selected_boot_partition(bs);
    post_native = true;
    return result;
}
#define CHECK(condition) do { if (!(condition)) { \
    fprintf(stderr, "check failed at %d: %s\n", __LINE__, #condition); return 1; } } while (0)
static void reset_model(void)
{
    memset(flash_bytes, 0xff, sizeof(flash_bytes));
    memset(&model_layout, 0, sizeof(model_layout));
    model_layout.test = (esp_partition_pos_t){0x20000, 0x1c0000};
    model_layout.ota_info = (esp_partition_pos_t){0x9000, 8192};
    model_layout.ota[0] = (esp_partition_pos_t){MOSAICO_APPLICATION_ADDRESS, normal_capacity};
    model_layout.app_count = 1;
    normal_load_attempts = recovery_load_attempts = 0; loaded_address = 0;
    normal_image_valid = recovery_image_valid = true;
    reads = erases = writes = native_calls = 0;
    fail_read = fail_erase = fail_write = partial_erase = corrupt_write = cut_erase = cut_write = 0;
    flash_encrypted = secure_boot = false;
    table_ok = true; maintenance = false; native_override = 0; erase_failure_after_mutation = false;
    fail_post_native_read = post_native = false;
}
static void entry(unsigned index, uint32_t seq, uint32_t state)
{
    esp_ota_select_entry_t e;
    memset(&e, 0xff, sizeof(e)); e.ota_seq = seq; e.ota_state = state;
    e.crc = bootloader_common_ota_select_crc(&e);
    memcpy(flash_bytes + index * 4096, &e, sizeof(e));
}
static esp_ota_select_entry_t get_entry(unsigned index)
{ esp_ota_select_entry_t e; memcpy(&e, flash_bytes + index * 4096, sizeof(e)); return e; }
static int boot(void)
{ bootloader_state_t bs; return select_partition_number(&bs); }
static int state(void)
{
    const esp_partition_t app = {MOSAICO_APPLICATION_ADDRESS, normal_capacity, 4096, 0x10};
    esp_ota_img_states_t s = ESP_OTA_IMG_UNDEFINED;
    if (esp_ota_get_state_partition(&app, &s) != ESP_OK) return -1;
    return (int)s;
}
static void reset_faults(void)
{ reads = erases = writes = 0; fail_read = fail_erase = fail_write = partial_erase = cut_erase = cut_write = 0; }
int main(int argc, char **argv)
{
    if (argc != 3) return 2;
    normal_capacity = (uint32_t)strtoul(argv[2], NULL, 0);
    reset_model();
    const char *test = argv[1];
    if (!strcmp(test, "upstream_negative_control")) {
        entry(0, 1, ESP_OTA_IMG_VALID); entry(1, 2, ESP_OTA_IMG_PENDING_VERIFY);
        CHECK(state() == ESP_OTA_IMG_VALID);
        CHECK(idf188_selected_boot_partition(&model_layout) == 0);
        CHECK(get_entry(1).ota_state == ESP_OTA_IMG_ABORTED);
        reset_model(); entry(0, 2, ESP_OTA_IMG_ABORTED);
        CHECK(idf188_selected_boot_partition(&model_layout) == 0);
    } else if (!strcmp(test, "valid_alias_normalized")) {
        entry(0, 1, ESP_OTA_IMG_ABORTED); entry(1, 2, ESP_OTA_IMG_VALID);
        CHECK(state() == ESP_OTA_IMG_ABORTED);
        CHECK(boot() == 0); CHECK(state() == ESP_OTA_IMG_VALID);
        CHECK(erases == 1 && writes == 0 && native_calls == 0);
        CHECK(boot() == 0 && erases == 1);
    } else if (!strcmp(test, "fresh_new_trial_and_health")) {
        entry(0, 1, ESP_OTA_IMG_VALID);
        CHECK(esp_rewrite_ota_data(0x10) == ESP_OK); /* completed-transfer commit */
        CHECK(get_entry(0).ota_state == ESP_OTA_IMG_NEW);
        CHECK(boot() == 0 && state() == ESP_OTA_IMG_PENDING_VERIFY);
        CHECK(esp_ota_current_ota_is_workable(true) == ESP_OK);
        CHECK(boot() == 0 && state() == ESP_OTA_IMG_VALID);
    } else if (!strcmp(test, "pending_survives_consumed_intent")) {
        entry(0, 1, ESP_OTA_IMG_VALID); entry(1, 2, ESP_OTA_IMG_PENDING_VERIFY);
        maintenance = true; CHECK(boot() == TEST_APP_INDEX); maintenance = false;
        for (unsigned i = 0; i < 5; ++i) CHECK(boot() == TEST_APP_INDEX);
        CHECK(get_entry(1).ota_state == ESP_OTA_IMG_PENDING_VERIFY);
        CHECK(erases == 0 && writes == 0 && native_calls == 0);
    } else if (!strcmp(test, "lower_new_after_terminal_failure")) {
        for (unsigned copy = 0; copy < 2; ++copy) {
            for (uint32_t bad = ESP_OTA_IMG_INVALID; bad <= ESP_OTA_IMG_ABORTED; ++bad) {
                reset_model(); entry(copy, 5, ESP_OTA_IMG_VALID); entry(copy ^ 1, 8, bad);
                CHECK(boot() == TEST_APP_INDEX);
                /* Model a verified completed transfer through the actual pinned SDK.
                 * It excludes the higher bad copy and rewrites lower VALID in place. */
                CHECK(esp_rewrite_ota_data(0x10) == ESP_OK);
                CHECK(get_entry(copy).ota_seq == 5 && get_entry(copy).ota_state == ESP_OTA_IMG_NEW);
                CHECK(boot() == 0 && state() == ESP_OTA_IMG_PENDING_VERIFY);
                CHECK(get_entry(copy ^ 1).ota_seq == UINT32_MAX);
                CHECK(esp_ota_current_ota_is_workable(true) == ESP_OK);
                CHECK(boot() == 0 && state() == ESP_OTA_IMG_VALID);
            }
        }
    } else if (!strcmp(test, "fresh_trial_never_retries_unhealthy")) {
        entry(1, 8, ESP_OTA_IMG_NEW);
        CHECK(boot() == 0 && state() == ESP_OTA_IMG_PENDING_VERIFY);
        for (unsigned i = 0; i < 4; ++i) CHECK(boot() == TEST_APP_INDEX);
        CHECK(get_entry(1).ota_state == ESP_OTA_IMG_PENDING_VERIFY);
    } else if (!strcmp(test, "latest_terminal_rejects_old_valid")) {
        for (uint32_t bad = ESP_OTA_IMG_INVALID; bad <= ESP_OTA_IMG_ABORTED; ++bad) {
            reset_model(); entry(0, 5, ESP_OTA_IMG_VALID); entry(1, 8, bad);
            CHECK(boot() == TEST_APP_INDEX && native_calls == 0 && erases == 0);
        }
    } else if (!strcmp(test, "empty_corrupt_unknown_unconfirmed")) {
        CHECK(boot() == TEST_APP_INDEX && native_calls == 0);
        entry(0, 1, ESP_OTA_IMG_VALID); flash_bytes[31] ^= 1;
        CHECK(boot() == TEST_APP_INDEX);
        entry(0, 1, 0x12345678); CHECK(boot() == TEST_APP_INDEX);
        entry(0, 1, ESP_OTA_IMG_UNDEFINED); CHECK(boot() == TEST_APP_INDEX);
        entry(0, 0, ESP_OTA_IMG_VALID); CHECK(boot() == TEST_APP_INDEX);
        CHECK(erases == 0 && native_calls == 0);
    } else if (!strcmp(test, "equal_sequence_conflict")) {
        entry(0, 5, ESP_OTA_IMG_VALID); entry(1, 5, ESP_OTA_IMG_ABORTED);
        CHECK(boot() == TEST_APP_INDEX && erases == 0);
        entry(0, 5, ESP_OTA_IMG_NEW); CHECK(boot() == TEST_APP_INDEX);
        entry(0, 5, ESP_OTA_IMG_VALID); entry(1, 5, ESP_OTA_IMG_VALID);
        CHECK(boot() == 0 && state() == ESP_OTA_IMG_VALID);
    } else if (!strcmp(test, "ambiguous_imported_new")) {
        entry(0, 5, ESP_OTA_IMG_NEW); entry(1, 8, ESP_OTA_IMG_NEW);
        CHECK(boot() == TEST_APP_INDEX);
        for (uint32_t nonterminal = ESP_OTA_IMG_PENDING_VERIFY; nonterminal <= ESP_OTA_IMG_VALID; ++nonterminal) {
            entry(1, 8, nonterminal); CHECK(boot() == TEST_APP_INDEX);
        }
        entry(1, 8, ESP_OTA_IMG_UNDEFINED); CHECK(boot() == TEST_APP_INDEX);
        CHECK(erases == 0 && native_calls == 0);
    } else if (!strcmp(test, "exact_layout_required_before_maintenance")) {
        flash_encrypted = true; maintenance = true;
        CHECK(boot() == INVALID_INDEX && reads == 0 && erases == 0);
        reset_model(); secure_boot = true;
        CHECK(boot() == INVALID_INDEX && reads == 0 && erases == 0);
        reset_model(); maintenance = true; model_layout.factory = (esp_partition_pos_t){MOSAICO_APPLICATION_ADDRESS, normal_capacity};
        CHECK(boot() == INVALID_INDEX && erases == 0 && reads == 0);
        reset_model(); model_layout.ota[1] = model_layout.ota[0];
        CHECK(boot() == INVALID_INDEX);
        reset_model(); model_layout.ota[0].size--; CHECK(boot() == INVALID_INDEX);
        reset_model(); model_layout.ota[0].offset++; CHECK(boot() == INVALID_INDEX);
        reset_model(); model_layout.ota[0].size = 0; CHECK(boot() == INVALID_INDEX);
        reset_model(); model_layout.ota[0].size = MOSAICO_FLASH_BYTES; CHECK(boot() == INVALID_INDEX);
        reset_model(); model_layout.ota_info.offset++; CHECK(boot() == INVALID_INDEX);
        reset_model(); model_layout.test.size--; CHECK(boot() == INVALID_INDEX);
        reset_model(); model_layout.app_count = 2; CHECK(boot() == INVALID_INDEX);
        reset_model(); table_ok = false; CHECK(boot() == INVALID_INDEX);
        CHECK(reads == 0 && erases == 0 && writes == 0);
    } else if (!strcmp(test, "initial_and_peer_read_fail_before_erase")) {
        entry(0, 1, ESP_OTA_IMG_VALID); entry(1, 2, ESP_OTA_IMG_NEW);
        for (unsigned call = 1; call <= 3; ++call) {
            reads = 0; fail_read = call; CHECK(boot() == TEST_APP_INDEX && erases == 0);
        }
    } else if (!strcmp(test, "peer_erase_failure_preserves_authority")) {
        entry(0, 1, ESP_OTA_IMG_VALID); entry(1, 2, ESP_OTA_IMG_NEW);
        fail_erase = 1; CHECK(boot() == TEST_APP_INDEX);
        CHECK(get_entry(1).ota_state == ESP_OTA_IMG_NEW && native_calls == 0);
        erase_failure_after_mutation = true; erases = 0;
        CHECK(boot() == TEST_APP_INDEX && get_entry(1).ota_state == ESP_OTA_IMG_NEW);
    } else if (!strcmp(test, "peer_full_sector_readback")) {
        entry(0, 1, ESP_OTA_IMG_VALID); entry(1, 2, ESP_OTA_IMG_NEW);
        partial_erase = 1; CHECK(boot() == TEST_APP_INDEX && native_calls == 0);
        CHECK(get_entry(1).ota_state == ESP_OTA_IMG_NEW);
    } else if (!strcmp(test, "native_ignored_erase_failure")) {
        entry(0, 1, ESP_OTA_IMG_NEW); fail_erase = 1;
        CHECK(boot() == TEST_APP_INDEX && native_calls == 1);
        CHECK(get_entry(0).ota_state == ESP_OTA_IMG_NEW);
    } else if (!strcmp(test, "native_ignored_write_failure")) {
        entry(0, 1, ESP_OTA_IMG_NEW); fail_write = 1;
        CHECK(boot() == TEST_APP_INDEX && native_calls == 1);
        reset_faults(); CHECK(boot() == TEST_APP_INDEX);
    } else if (!strcmp(test, "native_corrupt_write")) {
        entry(0, 1, ESP_OTA_IMG_NEW); corrupt_write = 1;
        CHECK(boot() == TEST_APP_INDEX && native_calls == 1);
    } else if (!strcmp(test, "pending_readback_failure")) {
        entry(1, 1, ESP_OTA_IMG_NEW); fail_post_native_read = true;
        CHECK(boot() == TEST_APP_INDEX && native_calls == 1);
        CHECK(get_entry(1).ota_state == ESP_OTA_IMG_PENDING_VERIFY);
    } else if (!strcmp(test, "corrupt_peer_cannot_alias_state")) {
        entry(0, 5, ESP_OTA_IMG_PENDING_VERIFY); flash_bytes[31] ^= 1;
        entry(1, 8, ESP_OTA_IMG_NEW);
        CHECK(boot() == 0 && state() == ESP_OTA_IMG_PENDING_VERIFY);
        CHECK(get_entry(0).ota_seq == UINT32_MAX);
    } else if (!strcmp(test, "power_cut_during_peer_normalization")) {
        entry(0, 1, ESP_OTA_IMG_VALID); entry(1, 2, ESP_OTA_IMG_NEW); cut_erase = 1;
        if (!setjmp(power_cut)) { (void)boot(); CHECK(false); }
        CHECK(get_entry(1).ota_state == ESP_OTA_IMG_NEW); reset_faults();
        CHECK(boot() == 0 && state() == ESP_OTA_IMG_PENDING_VERIFY);
    } else if (!strcmp(test, "power_cut_native_erase_fails_closed")) {
        entry(0, 1, ESP_OTA_IMG_NEW); cut_erase = 1;
        if (!setjmp(power_cut)) { (void)boot(); CHECK(false); }
        reset_faults(); CHECK(boot() == TEST_APP_INDEX);
    } else if (!strcmp(test, "power_cut_after_pending_write")) {
        entry(0, 1, ESP_OTA_IMG_NEW); cut_write = 1;
        if (!setjmp(power_cut)) { (void)boot(); CHECK(false); }
        reset_faults(); CHECK(boot() == TEST_APP_INDEX);
        CHECK(state() == ESP_OTA_IMG_PENDING_VERIFY);
    } else if (!strcmp(test, "bad_native_index_no_app_fallback")) {
        entry(0, 1, ESP_OTA_IMG_NEW); native_override = FACTORY_INDEX;
        CHECK(boot() == TEST_APP_INDEX);
        native_override = INVALID_INDEX; CHECK(boot() == TEST_APP_INDEX);
    } else if (!strcmp(test, "loader_image_failure_stays_in_recovery")) {
        int exit_code = setjmp(loader_exit);
        if (!exit_code) bootloader_utility_load_boot_image(&model_layout, 0);
        CHECK(exit_code == 1 && loaded_address == MOSAICO_APPLICATION_ADDRESS);
        CHECK(normal_load_attempts == 1 && recovery_load_attempts == 0);
        reset_model(); normal_image_valid = false;
        exit_code = setjmp(loader_exit);
        if (!exit_code) bootloader_utility_load_boot_image(&model_layout, 0);
        CHECK(exit_code == 1 && loaded_address == MOSAICO_RECOVERY_ADDRESS);
        CHECK(normal_load_attempts == 1 && recovery_load_attempts == 1);
        reset_model(); normal_image_valid = recovery_image_valid = false;
        exit_code = setjmp(loader_exit);
        if (!exit_code) bootloader_utility_load_boot_image(&model_layout, 0);
        CHECK(exit_code == 2 && loaded_address == 0);
        CHECK(normal_load_attempts == 1 && recovery_load_attempts == 1);
        reset_model(); recovery_image_valid = false;
        exit_code = setjmp(loader_exit);
        if (!exit_code) bootloader_utility_load_boot_image(&model_layout, TEST_APP_INDEX);
        CHECK(exit_code == 2 && normal_load_attempts == 0 && recovery_load_attempts == 1);
    } else if (!strcmp(test, "sequence_upper_boundary")) {
        entry(0, UINT32_MAX - 1, ESP_OTA_IMG_NEW);
        CHECK(boot() == 0 && state() == ESP_OTA_IMG_PENDING_VERIFY);
        CHECK(esp_ota_current_ota_is_workable(true) == ESP_OK && boot() == 0);
    } else return 2;
    puts(test); return 0;
}
'''

CASES = (
    "upstream_negative_control", "valid_alias_normalized", "fresh_new_trial_and_health",
    "pending_survives_consumed_intent", "lower_new_after_terminal_failure",
    "fresh_trial_never_retries_unhealthy", "latest_terminal_rejects_old_valid",
    "empty_corrupt_unknown_unconfirmed", "equal_sequence_conflict", "ambiguous_imported_new",
    "exact_layout_required_before_maintenance", "initial_and_peer_read_fail_before_erase",
    "peer_erase_failure_preserves_authority", "peer_full_sector_readback",
    "native_ignored_erase_failure", "native_ignored_write_failure", "native_corrupt_write",
    "pending_readback_failure", "corrupt_peer_cannot_alias_state",
    "power_cut_during_peer_normalization", "power_cut_native_erase_fails_closed",
    "power_cut_after_pending_write", "bad_native_index_no_app_fallback", "sequence_upper_boundary",
    "loader_image_failure_stays_in_recovery",
)


class SingleSlotPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        commit = subprocess.check_output(["git", "-C", str(IDF), "rev-parse", "HEAD"], text=True).strip()
        if commit != IDF_COMMIT:
            raise AssertionError("Host model requires the exact IDF188 checkout")
        if subprocess.check_output(["git", "-C", str(IDF), "diff", "--name-only", "HEAD", "--"], text=True).strip():
            raise AssertionError("Host model requires an unmodified pinned IDF checkout")
        candidate = (PROJECT / "bootloader_components/main/bootloader_start.c").read_text()
        common = (IDF / "components/bootloader_support/src/bootloader_common_loader.c").read_text()
        utility = (IDF / "components/bootloader_support/src/bootloader_utility.c").read_text()
        ota = (IDF / "components/app_update/esp_ota_ops.c").read_text()
        types = (IDF / "components/bootloader_support/include/esp_flash_partitions.h").read_text()
        ota_types = types[types.index("typedef enum {\n    ESP_OTA_IMG_NEW"):types.index("\n\n\ntypedef struct", types.index("} esp_ota_select_entry_t;"))]
        begin = candidate.index("/* BEGIN MOSAICO_SINGLE_SLOT_POLICY")
        end = candidate.index("/* END MOSAICO_SINGLE_SLOT_POLICY */", begin)
        policy = candidate[begin:end]
        if candidate.count("bootloader_utility_get_selected_boot_partition(bs)") != 1:
            raise AssertionError("Unexpected unguarded native selection path")
        if "bootloader_utility_load_boot_image_from_deep_sleep();" in candidate:
            raise AssertionError("Deep-sleep bypasses the metadata guard")
        source = "\n".join([
            PREAMBLE.replace("static int bootloader_common_select_otadata", ota_types + "\nstatic int bootloader_common_select_otadata", 1),
            *[function(common, name) for name in (
                "bootloader_common_ota_select_crc", "bootloader_common_ota_select_invalid",
                "bootloader_common_ota_select_valid", "bootloader_common_get_active_otadata",
                "bootloader_common_select_otadata")],
            function(utility, "write_otadata"),
            function(utility, "bootloader_utility_get_selected_boot_partition").replace(
                "bootloader_utility_get_selected_boot_partition(", "idf188_selected_boot_partition(", 1),
            *[function(ota, name) for name in (
                "set_new_state_otadata", "rewrite_ota_seq", "compute_ota_seq_for_target_slot",
                "esp_rewrite_ota_data", "esp_ota_get_state_partition", "esp_ota_current_ota_is_workable")],
            function(utility, "bootloader_utility_load_boot_image"),
            policy, function(candidate, "selected_boot_partition"), function(candidate, "select_partition_number"), MODEL,
        ])
        cls.temp = tempfile.TemporaryDirectory(prefix="mosaico-boot-policy-")
        cls.addClassCleanup(cls.temp.cleanup)
        c_file = Path(cls.temp.name) / "single_slot_policy.c"
        c_file.write_text(source)
        cls.executable = c_file.with_suffix("")
        subprocess.run([*shlex.split(os.environ.get("CC", "cc")), "-std=c11", "-Wall", "-Wextra", "-Werror",
                        "-O0", "-I" + str(PROJECT.parents[1] / "include"), str(c_file), "-o", str(cls.executable)], check=True)
        print(json.dumps({"idf_commit": commit, "candidate_bootloader_sha256":
            hashlib.sha256(candidate.encode()).hexdigest(), "compiled_host_cases": len(CASES) * 2, "normal_capacities": ["0xdf0000", "0x700000"]}))


def add_case(name: str) -> None:
    def run(self: SingleSlotPolicyTests) -> None:
        for capacity in ("0xdf0000", "0x700000"):
            with self.subTest(normal_capacity=capacity):
                result = subprocess.run([str(self.executable), name, capacity], text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
    setattr(SingleSlotPolicyTests, "test_" + name, run)


for case in CASES:
    add_case(case)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-project", type=Path, required=True)
    parser.add_argument("--idf-path", type=Path, required=True)
    args, remaining = parser.parse_known_args()
    PROJECT, IDF = args.candidate_project.resolve(), args.idf_path.resolve()
    unittest.main(argv=[__file__, *remaining], verbosity=2)
