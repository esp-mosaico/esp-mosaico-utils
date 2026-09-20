// SPDX-License-Identifier: Apache-2.0
/* This fixed-asset UI contains only GSPC-generated RGB565+A8 images. It has no
 * dynamic image provider. The 1.2.0 prebuilt GSP archive references its optional
 * JPEG decoder unconditionally; reject that unused format at the public JPEG
 * API boundary so the software codec does not occupy the immutable slot.
 * Re-enable the codec before adding JPEG or dynamic image features. */
#include "esp_jpeg_dec.h"
#include <stddef.h>
jpeg_error_t __wrap_jpeg_dec_open(jpeg_dec_config_t *config, jpeg_dec_handle_t *decoder)
{
    (void)config;
    if (decoder) *decoder = NULL;
    return JPEG_ERR_UNSUPPORT_FMT;
}
jpeg_error_t __wrap_jpeg_dec_parse_header(jpeg_dec_handle_t decoder, jpeg_dec_io_t *io, jpeg_dec_header_info_t *info)
{
    (void)decoder; (void)io; (void)info;
    return JPEG_ERR_UNSUPPORT_FMT;
}
jpeg_error_t __wrap_jpeg_dec_process(jpeg_dec_handle_t decoder, jpeg_dec_io_t *io)
{
    (void)decoder; (void)io;
    return JPEG_ERR_UNSUPPORT_FMT;
}
jpeg_error_t __wrap_jpeg_dec_close(jpeg_dec_handle_t decoder)
{
    (void)decoder;
    return JPEG_ERR_UNSUPPORT_FMT;
}
