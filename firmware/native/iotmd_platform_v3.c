// Versioned native platform capability boundary for the IoT-MD v3 alpha.

#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include "py/mpconfig.h"
#include "py/mperrno.h"
#include "py/obj.h"
#include "py/runtime.h"

#include "esp_flash_encrypt.h"
#include "esp_ota_ops.h"
#include "esp_partition.h"
#include "esp_psram.h"
#include "esp_secure_boot.h"
#include "nvs.h"
#include "sdkconfig.h"

#define IOTMD_PLATFORM_V3_ABI_VERSION (2)
#define IOTMD_V3_STORAGE_HANDLES (4)
#define IOTMD_V3_STORAGE_MAX_PAYLOAD (4096)
#define IOTMD_V3_STORAGE_HEADER_BYTES (16)

typedef struct {
    bool used;
    nvs_handle_t nvs;
} iotmd_v3_storage_handle_t;

static iotmd_v3_storage_handle_t iotmd_v3_storage_handles[
    IOTMD_V3_STORAGE_HANDLES
];

static void iotmd_v3_dict_store(mp_obj_t dictionary, qstr key,
    mp_obj_t value);

static uint32_t iotmd_v3_u32_read(const uint8_t *value) {
    return ((uint32_t)value[0]) | ((uint32_t)value[1] << 8) |
        ((uint32_t)value[2] << 16) | ((uint32_t)value[3] << 24);
}

static void iotmd_v3_u32_write(uint8_t *value, uint32_t number) {
    value[0] = number & 0xff;
    value[1] = (number >> 8) & 0xff;
    value[2] = (number >> 16) & 0xff;
    value[3] = (number >> 24) & 0xff;
}

static uint32_t iotmd_v3_crc32(const uint8_t *value, size_t length) {
    uint32_t crc = 0xffffffff;
    for (size_t index = 0; index < length; ++index) {
        crc ^= value[index];
        for (unsigned bit = 0; bit < 8; ++bit) {
            crc = (crc >> 1) ^ (0xedb88320 & (0 - (crc & 1)));
        }
    }
    return ~crc;
}

static iotmd_v3_storage_handle_t *iotmd_v3_storage_handle(mp_obj_t value) {
    mp_int_t identifier = mp_obj_get_int(value);
    if (identifier < 1 || identifier > IOTMD_V3_STORAGE_HANDLES ||
            !iotmd_v3_storage_handles[identifier - 1].used) {
        mp_raise_ValueError(MP_ERROR_TEXT("invalid storage handle"));
    }
    return &iotmd_v3_storage_handles[identifier - 1];
}

static bool iotmd_v3_storage_read_slot(nvs_handle_t nvs, const char *key,
        uint32_t *generation, mp_obj_t *payload) {
    size_t length = 0;
    esp_err_t error = nvs_get_blob(nvs, key, NULL, &length);
    if (error == ESP_ERR_NVS_NOT_FOUND) {
        return false;
    }
    if (error != ESP_OK || length < IOTMD_V3_STORAGE_HEADER_BYTES ||
            length > IOTMD_V3_STORAGE_HEADER_BYTES +
                IOTMD_V3_STORAGE_MAX_PAYLOAD) {
        return false;
    }
    uint8_t *buffer = m_new(uint8_t, length);
    error = nvs_get_blob(nvs, key, buffer, &length);
    if (error != ESP_OK || memcmp(buffer, "I3TX", 4) != 0) {
        m_del(uint8_t, buffer, length);
        return false;
    }
    uint32_t payload_length = iotmd_v3_u32_read(buffer + 8);
    uint32_t expected_crc = iotmd_v3_u32_read(buffer + 12);
    if (payload_length != length - IOTMD_V3_STORAGE_HEADER_BYTES ||
            iotmd_v3_crc32(buffer + IOTMD_V3_STORAGE_HEADER_BYTES,
                payload_length) != expected_crc) {
        m_del(uint8_t, buffer, length);
        return false;
    }
    *generation = iotmd_v3_u32_read(buffer + 4);
    *payload = mp_obj_new_bytes(
        buffer + IOTMD_V3_STORAGE_HEADER_BYTES, payload_length
    );
    m_del(uint8_t, buffer, length);
    return true;
}

static bool iotmd_v3_storage_latest(nvs_handle_t nvs, uint32_t *generation,
        mp_obj_t *payload) {
    uint32_t generation_a = 0;
    uint32_t generation_b = 0;
    mp_obj_t payload_a = mp_const_none;
    mp_obj_t payload_b = mp_const_none;
    bool valid_a = iotmd_v3_storage_read_slot(
        nvs, "snapshot_a", &generation_a, &payload_a
    );
    bool valid_b = iotmd_v3_storage_read_slot(
        nvs, "snapshot_b", &generation_b, &payload_b
    );
    if (!valid_a && !valid_b) {
        *generation = 0;
        *payload = mp_obj_new_bytes(NULL, 0);
        return false;
    }
    if (valid_b && (!valid_a || generation_b > generation_a)) {
        *generation = generation_b;
        *payload = payload_b;
    } else {
        *generation = generation_a;
        *payload = payload_a;
    }
    return true;
}

static mp_obj_t iotmd_platform_v3_storage_open(mp_obj_t namespace_in) {
#if !CONFIG_NVS_ENCRYPTION
    mp_raise_msg(
        &mp_type_RuntimeError, MP_ERROR_TEXT("encrypted NVS is unavailable")
    );
#else
    size_t length = 0;
    const char *name = mp_obj_str_get_data(namespace_in, &length);
    if (length == 0 || length > 15) {
        mp_raise_ValueError(MP_ERROR_TEXT("invalid storage namespace"));
    }
    for (size_t index = 0; index < length; ++index) {
        char value = name[index];
        if (!((value >= 'a' && value <= 'z') ||
                (value >= 'A' && value <= 'Z') ||
                (value >= '0' && value <= '9') || value == '_' ||
                value == '-')) {
            mp_raise_ValueError(MP_ERROR_TEXT("invalid storage namespace"));
        }
    }
    for (size_t index = 0; index < IOTMD_V3_STORAGE_HANDLES; ++index) {
        if (!iotmd_v3_storage_handles[index].used) {
            char bounded_name[16];
            memcpy(bounded_name, name, length);
            bounded_name[length] = '\0';
            esp_err_t error = nvs_open(
                bounded_name, NVS_READWRITE,
                &iotmd_v3_storage_handles[index].nvs
            );
            if (error != ESP_OK) {
                mp_raise_OSError(error);
            }
            iotmd_v3_storage_handles[index].used = true;
            return MP_OBJ_NEW_SMALL_INT(index + 1);
        }
    }
    mp_raise_msg(
        &mp_type_RuntimeError, MP_ERROR_TEXT("storage handle limit reached")
    );
#endif
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(
    iotmd_platform_v3_storage_open_obj, iotmd_platform_v3_storage_open
);

static mp_obj_t iotmd_platform_v3_storage_close(mp_obj_t handle_in) {
    iotmd_v3_storage_handle_t *handle = iotmd_v3_storage_handle(handle_in);
    nvs_close(handle->nvs);
    handle->used = false;
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(
    iotmd_platform_v3_storage_close_obj, iotmd_platform_v3_storage_close
);

static mp_obj_t iotmd_platform_v3_storage_snapshot(mp_obj_t handle_in) {
    iotmd_v3_storage_handle_t *handle = iotmd_v3_storage_handle(handle_in);
    uint32_t generation = 0;
    mp_obj_t payload = mp_const_none;
    iotmd_v3_storage_latest(handle->nvs, &generation, &payload);
    mp_obj_t result = mp_obj_new_dict(2);
    iotmd_v3_dict_store(
        result, MP_QSTR_generation, mp_obj_new_int_from_uint(generation)
    );
    iotmd_v3_dict_store(result, MP_QSTR_payload, payload);
    return result;
}
static MP_DEFINE_CONST_FUN_OBJ_1(
    iotmd_platform_v3_storage_snapshot_obj,
    iotmd_platform_v3_storage_snapshot
);

static mp_obj_t iotmd_platform_v3_storage_commit(size_t n_args,
        const mp_obj_t *args) {
    iotmd_v3_storage_handle_t *handle = iotmd_v3_storage_handle(args[0]);
    mp_int_t expected = mp_obj_get_int(args[1]);
    if (expected < 0 || (uint64_t)expected > UINT32_MAX) {
        mp_raise_ValueError(MP_ERROR_TEXT("invalid storage generation"));
    }
    mp_buffer_info_t source;
    mp_get_buffer_raise(args[2], &source, MP_BUFFER_READ);
    if (source.len > IOTMD_V3_STORAGE_MAX_PAYLOAD) {
        mp_raise_ValueError(MP_ERROR_TEXT("storage payload too large"));
    }
    uint32_t current = 0;
    mp_obj_t ignored = mp_const_none;
    iotmd_v3_storage_latest(handle->nvs, &current, &ignored);
    if ((uint32_t)expected != current) {
        mp_raise_OSError(MP_EAGAIN);
    }
    if (current == UINT32_MAX) {
        mp_raise_msg(
            &mp_type_RuntimeError,
            MP_ERROR_TEXT("storage generation exhausted")
        );
    }
    uint32_t next = current + 1;
    size_t length = IOTMD_V3_STORAGE_HEADER_BYTES + source.len;
    uint8_t *buffer = m_new(uint8_t, length);
    memcpy(buffer, "I3TX", 4);
    iotmd_v3_u32_write(buffer + 4, next);
    iotmd_v3_u32_write(buffer + 8, source.len);
    iotmd_v3_u32_write(
        buffer + 12, iotmd_v3_crc32(source.buf, source.len)
    );
    memcpy(buffer + IOTMD_V3_STORAGE_HEADER_BYTES, source.buf, source.len);
    const char *key = (next & 1) ? "snapshot_b" : "snapshot_a";
    esp_err_t error = nvs_set_blob(handle->nvs, key, buffer, length);
    if (error == ESP_OK) {
        error = nvs_commit(handle->nvs);
    }
    m_del(uint8_t, buffer, length);
    if (error != ESP_OK) {
        mp_raise_OSError(error);
    }
    return mp_obj_new_int_from_uint(next);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(
    iotmd_platform_v3_storage_commit_obj, 3, 3,
    iotmd_platform_v3_storage_commit
);

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

    mp_obj_t storage = mp_obj_new_dict(4);
#if CONFIG_NVS_ENCRYPTION
    iotmd_v3_dict_store(storage, MP_QSTR_encrypted, mp_const_true);
    iotmd_v3_dict_store(storage, MP_QSTR_transactional, mp_const_true);
#else
    iotmd_v3_dict_store(storage, MP_QSTR_encrypted, mp_const_false);
    iotmd_v3_dict_store(storage, MP_QSTR_transactional, mp_const_false);
#endif
    iotmd_v3_dict_store(
        storage, MP_QSTR_max_namespaces,
        MP_OBJ_NEW_SMALL_INT(IOTMD_V3_STORAGE_HANDLES)
    );
    iotmd_v3_dict_store(
        storage, MP_QSTR_max_payload_bytes,
        MP_OBJ_NEW_SMALL_INT(IOTMD_V3_STORAGE_MAX_PAYLOAD)
    );

    mp_obj_t updates = mp_obj_new_dict(3);
    iotmd_v3_dict_store(updates, MP_QSTR_paired_manifest, mp_const_true);
    iotmd_v3_dict_store(updates, MP_QSTR_paired_trial, mp_const_false);
    iotmd_v3_dict_store(updates, MP_QSTR_native_rollback, mp_const_false);

    mp_obj_t result = mp_obj_new_dict(8);
    iotmd_v3_dict_store(
        result, MP_QSTR_abi_version,
        MP_OBJ_NEW_SMALL_INT(IOTMD_PLATFORM_V3_ABI_VERSION)
    );
    iotmd_v3_dict_store(result, MP_QSTR_board, board);
    iotmd_v3_dict_store(result, MP_QSTR_runtime, runtime);
    iotmd_v3_dict_store(result, MP_QSTR_security, security);
    iotmd_v3_dict_store(result, MP_QSTR_memory, memory);
    iotmd_v3_dict_store(result, MP_QSTR_interfaces, interfaces);
    iotmd_v3_dict_store(result, MP_QSTR_storage, storage);
    iotmd_v3_dict_store(result, MP_QSTR_updates, updates);
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
    { MP_ROM_QSTR(MP_QSTR_storage_open),
      MP_ROM_PTR(&iotmd_platform_v3_storage_open_obj) },
    { MP_ROM_QSTR(MP_QSTR_storage_close),
      MP_ROM_PTR(&iotmd_platform_v3_storage_close_obj) },
    { MP_ROM_QSTR(MP_QSTR_storage_snapshot),
      MP_ROM_PTR(&iotmd_platform_v3_storage_snapshot_obj) },
    { MP_ROM_QSTR(MP_QSTR_storage_commit),
      MP_ROM_PTR(&iotmd_platform_v3_storage_commit_obj) },
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
