"""FIFO adaptation preserves interface storage and rejects incomplete rewrites."""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

COMPONENT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("fifo_adapter", COMPONENT / "cmake/usb_fifo_psram.py")
ADAPTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ADAPTER)

SOURCE = '''#include "cdc_device.h"
typedef struct {
  uint8_t dma[32];
  uint8_t tx_ff_buf[CFG_TUD_CDC_TX_BUFSIZE];
  uint8_t rx_ff_buf[CFG_TUD_CDC_RX_BUFSIZE];
  uint8_t *tx;
  uint8_t *rx;
} cdcd_interface_t;
static cdcd_interface_t _cdcd_itf[CFG_TUD_CDC];
static void initialize(void) {
  for (unsigned index = 0; index < CFG_TUD_CDC; ++index) {
    cdcd_interface_t *p_cdc = &_cdcd_itf[index];
    p_cdc->tx = p_cdc->tx_ff_buf;
    p_cdc->rx = p_cdc->rx_ff_buf;
  }
}
'''


@pytest.mark.parametrize("formatting", [False, True])
def test_fifo_storage_survives_upstream_edits(tmp_path, formatting):
    source = "/* A new upstream revision with unrelated changes. */\n" + SOURCE
    if formatting:
        source = source.replace("[CFG_", "[ CFG_").replace("p_cdc->", "p_cdc -> ")
    generated = ADAPTER.adapt(source.encode())
    headers = tmp_path / "class/cdc"
    headers.mkdir(parents=True)
    (headers / "cdc_device.h").write_text(
        '#include <stdint.h>\n#define CFG_TUD_CDC 2\n'
        '#define CFG_TUD_CDC_TX_BUFSIZE 8\n#define CFG_TUD_CDC_RX_BUFSIZE 16\n')
    (tmp_path / "esp_attr.h").write_text('#define EXT_RAM_BSS_ATTR\n')
    main = tmp_path / "adapted.c"
    main.write_bytes(generated + b'''
#include <assert.h>
int main(void) {
  initialize();
  for (unsigned n = 0; n < CFG_TUD_CDC; ++n) {
    for (unsigned j = 0; j < CFG_TUD_CDC_TX_BUFSIZE; ++j) _cdcd_itf[n].tx[j] = 10 + n;
    for (unsigned j = 0; j < CFG_TUD_CDC_RX_BUFSIZE; ++j) _cdcd_itf[n].rx[j] = 20 + n;
    _cdcd_itf[n].dma[31] = 30 + n;
  }
  for (unsigned n = 0; n < CFG_TUD_CDC; ++n) {
    assert(_cdcd_itf[n].tx[7] == 10 + n);
    assert(_cdcd_itf[n].rx[15] == 20 + n);
    assert(_cdcd_itf[n].dma[31] == 30 + n);
    assert(_cdcd_itf[n].tx != _cdcd_itf[n].rx);
  }
  assert(_cdcd_itf[0].tx != _cdcd_itf[1].tx);
  assert(_cdcd_itf[0].rx != _cdcd_itf[1].rx);
  return 0;
}
''')
    binary = tmp_path / "fifo-test"
    subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-I" + str(tmp_path),
                    str(main), "-o", str(binary)], check=True, capture_output=True, timeout=30)
    subprocess.run([str(binary)], check=True, capture_output=True, timeout=10)


@pytest.mark.parametrize("source", [
    SOURCE.replace("uint8_t tx_ff_buf", "uint16_t tx_ff_buf"),
    SOURCE.replace("p_cdc->rx_ff_buf", "another->rx_ff_buf"),
    SOURCE.replace("static cdcd_interface_t _cdcd_itf[CFG_TUD_CDC];", ""),
])
def test_incompatible_fifo_layout_is_rejected(source):
    with pytest.raises(ValueError, match="Unsupported TinyUSB CDC"):
        ADAPTER.adapt(source.encode())


def test_fifo_adapter_rejects_unknown_source_without_touching_output(tmp_path):
    source = tmp_path / "upstream.c"
    output = tmp_path / "generated.c"
    source.write_bytes(b"/* unreviewed upstream revision */\n")
    output.write_bytes(b"previous build artifact\n")
    result = subprocess.run([sys.executable, str(COMPONENT / "cmake/usb_fifo_psram.py"),
                             str(source), str(output)], capture_output=True, text=True, check=False)
    assert result.returncode != 0
    assert "Unsupported TinyUSB CDC layout" in result.stderr
    assert source.read_bytes() == b"/* unreviewed upstream revision */\n"
    assert output.read_bytes() == b"previous build artifact\n"
