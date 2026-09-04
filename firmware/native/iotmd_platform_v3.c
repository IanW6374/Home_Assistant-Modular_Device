// Versioned native platform capability boundary for the IoT-MD v3 alpha.

#include <stdbool.h>

#include "py/mpconfig.h"
#include "py/obj.h"
#include "py/runtime.h"

#include "esp_flash_encrypt.h"
#include "esp_ota_ops.h"
#include "esp_partition.h"
#include "esp_psram.h"
#include "esp_secure_boot.h"
#include "sdkconfig.h"

#define IOTMD_PLATFORM_V3_ABI_VERSION (1)

static void iotmd_v3_dict_store(mp_obj_t dictionary, qstr key,
    mp_obj_t value) {
    mp_obj_dict_store(dictionary, MP_OBJ_NEW_QSTR(key), value);
}

static mp_obj_t iotmd_platform_v3_capabilities(void) {
    const esp_partition_t *running = esp_ota_get_running_partition();
    size_t ota_partition_bytes = running == NULL ? 0 : running->size;

    mp_obj_t board = mp_obj_new_dict(2);
    iotmd_v3_dict_store(
        board, MP_QSTR_target,
        mp_obj_new_str("esp32-s3", sizeof("esp32-s3") - 1)
    );
    iotmd_v3_dict_store(
        board, MP_QSTR_revision,
        mp_obj_new_str("devkitc-n8r8", sizeof("devkitc-n8r8") - 1)
    );

    mp_obj_t runtime = mp_obj_new_dict(3);
    iotmd_v3_dict_store(
        runtime, MP_QSTR_engine,
        mp_obj_new_str("micropython", sizeof("micropython") - 1)
    );
    iotmd_v3_dict_store(
        runtime, MP_QSTR_version,
        mp_obj_new_str(MICROPY_VERSION_STRING, sizeof(MICROPY_VERSION_STRING) - 1)
    );
    iotmd_v3_dict_store(
        runtime, MP_QSTR_platform_abi,
        MP_OBJ_NEW_SMALL_INT(IOTMD_PLATFORM_V3_ABI_VERSION)
    );

    mp_obj_t security = mp_obj_new_dict(3);
    iotmd_v3_dict_store(
        security, MP_QSTR_secure_boot,
        mp_obj_new_bool(esp_secure_boot_enabled())
    );
    iotmd_v3_dict_store(
        security, MP_QSTR_flash_encryption,
        mp_obj_new_bool(esp_flash_encryption_enabled())
    );
#if CONFIG_NVS_ENCRYPTION
    iotmd_v3_dict_store(security, MP_QSTR_encrypted_nvs, mp_const_true);
#else
    iotmd_v3_dict_store(security, MP_QSTR_encrypted_nvs, mp_const_false);
#endif

    size_t psram_bytes = esp_psram_get_size();
    mp_obj_t memory = mp_obj_new_dict(3);
    iotmd_v3_dict_store(
        memory, MP_QSTR_psram, mp_obj_new_bool(psram_bytes > 0)
    );
    iotmd_v3_dict_store(
        memory, MP_QSTR_psram_bytes, mp_obj_new_int_from_uint(psram_bytes)
    );
    iotmd_v3_dict_store(
        memory, MP_QSTR_ota_partition_bytes,
        mp_obj_new_int_from_uint(ota_partition_bytes)
    );

    mp_obj_t interfaces = mp_obj_new_dict(6);
#if CONFIG_ESP_WIFI_ENABLED
    iotmd_v3_dict_store(interfaces, MP_QSTR_wifi, mp_const_true);
#else
    iotmd_v3_dict_store(interfaces, MP_QSTR_wifi, mp_const_false);
#endif
#if CONFIG_IDF_TARGET_ESP32S3
    iotmd_v3_dict_store(interfaces, MP_QSTR_usb_device, mp_const_true);
    iotmd_v3_dict_store(
        interfaces, MP_QSTR_usb_ncm_hardware, mp_const_true
    );
#else
    iotmd_v3_dict_store(interfaces, MP_QSTR_usb_device, mp_const_false);
    iotmd_v3_dict_store(
        interfaces, MP_QSTR_usb_ncm_hardware, mp_const_false
    );
#endif
    // Alpha 1 defines the contract but deliberately does not claim an NCM
    // backend. These become true only after the native data path is qualified.
    iotmd_v3_dict_store(
        interfaces, MP_QSTR_usb_ncm_runtime, mp_const_false
    );
    iotmd_v3_dict_store(
        interfaces, MP_QSTR_usb_ncm_available, mp_const_false
    );
    iotmd_v3_dict_store(interfaces, MP_QSTR_ethernet, mp_const_false);

    mp_obj_t result = mp_obj_new_dict(6);
    iotmd_v3_dict_store(
        result, MP_QSTR_abi_version,
        MP_OBJ_NEW_SMALL_INT(IOTMD_PLATFORM_V3_ABI_VERSION)
    );
    iotmd_v3_dict_store(result, MP_QSTR_board, board);
    iotmd_v3_dict_store(result, MP_QSTR_runtime, runtime);
    iotmd_v3_dict_store(result, MP_QSTR_security, security);
    iotmd_v3_dict_store(result, MP_QSTR_memory, memory);
    iotmd_v3_dict_store(result, MP_QSTR_interfaces, interfaces);
    return result;
}
static MP_DEFINE_CONST_FUN_OBJ_0(
    iotmd_platform_v3_capabilities_obj,
    iotmd_platform_v3_capabilities
);

static const mp_rom_map_elem_t iotmd_platform_v3_module_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__),
      MP_ROM_QSTR(MP_QSTR__iotmd_platform_v3) },
    { MP_ROM_QSTR(MP_QSTR_ABI_VERSION),
      MP_ROM_INT(IOTMD_PLATFORM_V3_ABI_VERSION) },
    { MP_ROM_QSTR(MP_QSTR_capabilities),
      MP_ROM_PTR(&iotmd_platform_v3_capabilities_obj) },
};
static MP_DEFINE_CONST_DICT(
    iotmd_platform_v3_module_globals,
    iotmd_platform_v3_module_globals_table
);

const mp_obj_module_t iotmd_platform_v3_user_cmodule = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&iotmd_platform_v3_module_globals,
};

MP_REGISTER_MODULE(
    MP_QSTR__iotmd_platform_v3,
    iotmd_platform_v3_user_cmodule
);
