idf_component_register(
    SRCS "main.c" "iris_example.c" "media_assets.c"
    INCLUDE_DIRS "."
    REQUIRES esp_iris freertos
)
