set(IDF_TARGET esp32s3)

set(SDKCONFIG_DEFAULTS
    boards/sdkconfig.base
    # The base fragment enables the SPIRAM allocator. The SPIRAM_OCT
    # variant included below only changes the bus mode; using it alone leaves
    # CONFIG_SPIRAM disabled and limits MicroPython to internal RAM.
    boards/sdkconfig.spiram_quad
    ${MICROPY_BOARD_DIR}/sdkconfig.board
)

if(IOTMD_PRODUCTION_SECURITY)
    if(NOT IOTMD_SECURE_BOOT_SIGNING_KEY)
        message(FATAL_ERROR "IOTMD_SECURE_BOOT_SIGNING_KEY is required for production firmware")
    endif()
    file(WRITE ${CMAKE_BINARY_DIR}/sdkconfig.iotmd-signing-key
        "CONFIG_SECURE_BOOT_SIGNING_KEY=\"${IOTMD_SECURE_BOOT_SIGNING_KEY}\"\n")
    list(APPEND SDKCONFIG_DEFAULTS
        ${MICROPY_BOARD_DIR}/../../sdkconfig.production
        ${CMAKE_BINARY_DIR}/sdkconfig.iotmd-signing-key
    )
endif()
