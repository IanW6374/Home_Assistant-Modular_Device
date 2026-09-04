add_library(usermod_iotmd_crypto INTERFACE)

target_sources(usermod_iotmd_crypto INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}/iotmd_crypto.c
    ${CMAKE_CURRENT_LIST_DIR}/iotmd_platform.c
    ${CMAKE_CURRENT_LIST_DIR}/iotmd_platform_v3.c
)

target_include_directories(usermod_iotmd_crypto INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}
)

target_link_libraries(usermod INTERFACE usermod_iotmd_crypto)
