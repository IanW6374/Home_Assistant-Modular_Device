set(IDF_TARGET esp32s3)

set(SDKCONFIG_DEFAULTS
    boards/sdkconfig.base
    boards/sdkconfig.ble
    boards/sdkconfig.spiram_sx
    ${MICROPY_BOARD_DIR}/sdkconfig.board
)

if(HAM_PRODUCTION_SECURITY)
    if(NOT HAM_SECURE_BOOT_SIGNING_KEY)
        message(FATAL_ERROR "HAM_SECURE_BOOT_SIGNING_KEY is required for production firmware")
    endif()
    file(WRITE ${CMAKE_BINARY_DIR}/sdkconfig.ham-signing-key
        "CONFIG_SECURE_BOOT_SIGNING_KEY=\"${HAM_SECURE_BOOT_SIGNING_KEY}\"\n")
    list(APPEND SDKCONFIG_DEFAULTS
        ${MICROPY_BOARD_DIR}/../../sdkconfig.production
        ${CMAKE_BINARY_DIR}/sdkconfig.ham-signing-key
    )
endif()
