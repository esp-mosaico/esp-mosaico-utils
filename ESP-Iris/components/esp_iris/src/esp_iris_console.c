#include "esp_iris_console.h"
#include "sdkconfig.h"

#if CONFIG_ESP_IRIS_ENABLE && CONFIG_ESP_IRIS_CONSOLE_EXTERNAL_INPUT
#include "esp_console.h"
#include "esp_iris_internal.h"

_Static_assert(ESP_IRIS_CONSOLE_LINE_BYTES >= IRIS_CONSOLE_RECORD_BYTES,
               "public console line bound must contain a protocol record");

/* One shared input owner, bounded queue, no second driver reader. The lock
 * covers copies only; neither blocking I/O nor service work runs under it. */
static portMUX_TYPE s_input_lock = portMUX_INITIALIZER_UNLOCKED;
static char s_input[ESP_IRIS_CONSOLE_LINE_BYTES];
static size_t s_length;
static size_t s_offset;
static bool s_accepting;
static uint32_t s_generation;

/* The REPL is the sole driver reader. Yield to the Iris worker when its
 * one-line queue is occupied, without allocating another record buffer. */
#define IRIS_REPL_ADMISSION_TIMEOUT_MS 1000U

void iris_console_input_enable(bool enabled)
{
    taskENTER_CRITICAL(&s_input_lock);
    s_accepting = enabled;
    ++s_generation;
    s_length = 0;
    s_offset = 0;
    taskEXIT_CRITICAL(&s_input_lock);
}

bool iris_console_input_available(void)
{
    taskENTER_CRITICAL(&s_input_lock);
    const bool available = s_length > s_offset;
    taskEXIT_CRITICAL(&s_input_lock);
    return available;
}

int iris_console_input_read(uint8_t *buffer, size_t capacity)
{
    taskENTER_CRITICAL(&s_input_lock);
    size_t length = s_length - s_offset;
    if (length > capacity) length = capacity;
    memcpy(buffer, s_input + s_offset, length);
    s_offset += length;
    if (s_offset == s_length) s_length = s_offset = 0;
    taskEXIT_CRITICAL(&s_input_lock);
    return (int)length;
}

esp_err_t esp_iris_console_submit(const char *line, size_t length)
{
    if (line == NULL || length < 4 || length >= sizeof(s_input) ||
            memcmp(line, "iris", 4) != 0 || (length > 4 && line[4] != ' '))
        return ESP_ERR_INVALID_ARG;
    for (size_t i = 0; i < length; ++i) {
        if ((unsigned char)line[i] < 32 || (unsigned char)line[i] > 126)
            return ESP_ERR_INVALID_ARG;
    }
    taskENTER_CRITICAL(&s_input_lock);
    esp_err_t result = ESP_OK;
    if (!s_accepting) result = ESP_ERR_INVALID_STATE;
    else if (s_length != 0) result = ESP_ERR_TIMEOUT;
    else {
        memcpy(s_input, line, length);
        s_input[length] = '\n';
        s_length = length + 1;
        s_offset = 0;
    }
    taskEXIT_CRITICAL(&s_input_lock);
    return result;
}

static int iris_command(int argc, char **argv)
{
    /* Copy directly into the bounded queue, avoiding a large REPL stack. */
    if (argc != 1 && argc != 2) return ESP_ERR_INVALID_ARG;
    const char *argument = argc == 1 ? "help" : argv[1];
    const size_t length = strlen(argument);
    if (length + 6 > sizeof(s_input)) return ESP_ERR_INVALID_SIZE;
    for (size_t i = 0; i < length; ++i) {
        if ((unsigned char)argument[i] < 32 || (unsigned char)argument[i] > 126)
            return ESP_ERR_INVALID_ARG;
    }
    taskENTER_CRITICAL(&s_input_lock);
    const uint32_t generation = s_generation;
    taskEXIT_CRITICAL(&s_input_lock);
    const TickType_t started = xTaskGetTickCount();
    const TickType_t timeout = pdMS_TO_TICKS(IRIS_REPL_ADMISSION_TIMEOUT_MS);
    for (;;) {
        taskENTER_CRITICAL(&s_input_lock);
        esp_err_t result = ESP_OK;
        if (!s_accepting || generation != s_generation) result = ESP_ERR_INVALID_STATE;
        else if (s_length != 0) result = ESP_ERR_TIMEOUT;
        else {
            memcpy(s_input, "iris ", 5);
            memcpy(s_input + 5, argument, length);
            s_input[length + 5] = '\n';
            s_length = length + 6;
            s_offset = 0;
        }
        taskEXIT_CRITICAL(&s_input_lock);
        if (result != ESP_ERR_TIMEOUT || (TickType_t)(xTaskGetTickCount() - started) >= timeout)
            return result;
        /* Never wait under the spinlock. The worker drains the existing line
         * before this command is admitted once; execution is not retried. */
        vTaskDelay(1);
    }
}

esp_err_t esp_iris_console_register_commands(void)
{
    const esp_console_cmd_t command = {
        .command = "iris", .help = "Iris status, discovery and printable 0.2 API",
        .hint = "status|hello|help|@record", .func = iris_command,
    };
    return esp_console_cmd_register(&command);
}
#else
esp_err_t esp_iris_console_register_commands(void)
{
    return ESP_ERR_NOT_SUPPORTED;
}

esp_err_t esp_iris_console_submit(const char *line, size_t length)
{
    (void)line;
    (void)length;
    return ESP_ERR_NOT_SUPPORTED;
}
#endif
