"""Execute the product service provider against fallible host backends."""
from pathlib import Path
import subprocess
import textwrap

TOOLS = Path(__file__).resolve().parents[1]

def test_provider_failure_propagation_and_borrowed_interfaces(tmp_path):
    # The public neutral contracts are represented by small ABI fixtures here;
    # the actual Engine integration is separately built with ESP-IDF.
    (tmp_path / "raylib_lite_native_services.h").write_text(textwrap.dedent("""
        #pragma once
        #include <stdint.h>
        typedef int raylib_lite_result_t;
        enum {RAYLIB_LITE_OK=0, RAYLIB_LITE_INVALID_ARGUMENT=1,
              RAYLIB_LITE_PLATFORM_ERROR=9};
        typedef struct {uint16_t width,height;} raylib_lite_video_info_t;
        typedef struct {void *context; int (*get_info)(void *,raylib_lite_video_info_t *);} raylib_lite_video_backend_t;
        typedef struct {int unused;} raylib_lite_input_queue_t;
        typedef struct {int (*boot)(void);int (*attach)(raylib_lite_video_backend_t,raylib_lite_input_queue_t *);
                        int (*first_present)(void);int (*detach)(void);} raylib_lite_native_services_t;
        const raylib_lite_native_services_t *raylib_lite_native_services_get(void);
    """))
    (tmp_path / "raylib_lite_input.h").write_text('#include "raylib_lite_native_services.h"\n')
    (tmp_path / "raylib_lite_video.h").write_text('#include "raylib_lite_native_services.h"\n')
    (tmp_path / "esp_err.h").write_text('#pragma once\ntypedef int esp_err_t;\n#define ESP_OK 0\n')
    (tmp_path / "esp_iris.h").write_text('#include "esp_err.h"\nint esp_iris_boot_probe(void);\nint esp_iris_mark_healthy(void);\n')
    (tmp_path / "iris_ota_support.h").write_text('void iris_ota_support_start(void);\n')
    (tmp_path / "probe.c").write_text(textwrap.dedent("""
        #include <assert.h>
        #include <stddef.h>
        #include "raylib_lite_native_services.h"
        static int failure,start_calls,attach_calls,detach_calls;
        int esp_iris_boot_probe(void) {return failure;}
        void iris_ota_support_start(void) {++start_calls;}
        int esp_iris_mark_healthy(void) {return failure;}
        int mosaico_iris_display_input_register(raylib_lite_video_backend_t v,
                raylib_lite_input_queue_t *q,uint16_t w,uint16_t h) {
            assert(v.context==q && w==320 && h==240);++attach_calls;return failure;
        }
        int mosaico_iris_display_input_unregister(void) {++detach_calls;return failure;}
        static int info(void *ctx,raylib_lite_video_info_t *out) {
            assert(ctx);out->width=320;out->height=240;return failure;
        }
        int main(void) {
            const raylib_lite_native_services_t *s=raylib_lite_native_services_get();
            failure=1;assert(s->boot()==9 && start_calls==0);
            failure=0;assert(s->boot()==0 && start_calls==1);
            raylib_lite_input_queue_t q={0};
            raylib_lite_video_backend_t v={&q,info};
            failure=1;assert(s->attach(v,&q)==1 && attach_calls==0);
            failure=0;assert(s->attach(v,&q)==0 && attach_calls==1);
            assert(s->first_present()==0);failure=1;assert(s->first_present()==9);
            assert(s->detach()==9 && detach_calls==1);
            failure=0;assert(s->detach()==0 && detach_calls==2);
            v.get_info=NULL;assert(s->attach(v,&q)==1);
            return 0;
        }
    """))
    component = TOOLS / "components/esp_mosaico_raylib_iris"
    executable = tmp_path / "probe"
    subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", str(tmp_path),
                    str(component / "native_services.c"), str(tmp_path / "probe.c"),
                    "-o", str(executable)], check=True, capture_output=True)
    subprocess.run([str(executable)], check=True)
