add_library(usermod_hamd_crypto INTERFACE)

target_sources(usermod_hamd_crypto INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}/hamd_crypto.c
)

target_include_directories(usermod_hamd_crypto INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}
)

target_link_libraries(usermod INTERFACE usermod_hamd_crypto)
