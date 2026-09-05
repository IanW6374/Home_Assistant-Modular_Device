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
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "nvs.h"
#include "sdkconfig.h"

#define IOTMD_PLATFORM_V3_ABI_VERSION (4)
#define IOTMD_V3_STORAGE_HANDLES (4)
#define IOTMD_V3_STORAGE_MAX_PAYLOAD (4096)
#define IOTMD_V3_STORAGE_HEADER_BYTES (16)
#define IOTMD_V3_RESOURCE_CLAIMS (16)
#define IOTMD_V3_RESOURCE_KIND_BYTES (12)
#define IOTMD_V3_RESOURCE_IDENTIFIER_BYTES (32)
#define IOTMD_V3_RESOURCE_OWNER_BYTES (32)
#define IOTMD_V3_RECOVERY_REASON_BYTES (160)
#define IOTMD_V3_JOB_KIND_BYTES (24)
#define IOTMD_V3_JOB_ARGUMENT_BYTES (160)
#define IOTMD_V3_JOB_DETAIL_BYTES (96)
#define IOTMD_V3_JOB_QUEUE_DEPTH (4)
#define IOTMD_V3_EVENT_QUEUE_DEPTH (8)
#define IOTMD_V3_JOB_STACK_BYTES (4096)
#define IOTMD_V3_JOB_TIMEOUT_MS (5000)

typedef struct {
    bool used;
    nvs_handle_t nvs;
} iotmd_v3_storage_handle_t;

static iotmd_v3_storage_handle_t iotmd_v3_storage_handles[
    IOTMD_V3_STORAGE_HANDLES
];

typedef struct {
    bool used;
    char kind[IOTMD_V3_RESOURCE_KIND_BYTES + 1];
    char identifier[IOTMD_V3_RESOURCE_IDENTIFIER_BYTES + 1];
    char owner[IOTMD_V3_RESOURCE_OWNER_BYTES + 1];
} iotmd_v3_resource_claim_t;

static iotmd_v3_resource_claim_t iotmd_v3_resource_claims[
    IOTMD_V3_RESOURCE_CLAIMS
];

typedef struct {
    uint32_t identifier;
    char kind[IOTMD_V3_JOB_KIND_BYTES + 1];
    char argument[IOTMD_V3_JOB_ARGUMENT_BYTES + 1];
} iotmd_v3_job_t;

typedef struct {
    uint32_t identifier;
    char kind[IOTMD_V3_JOB_KIND_BYTES + 1];
    char status[12];
    int32_t error;
    char detail[IOTMD_V3_JOB_DETAIL_BYTES + 1];
} iotmd_v3_event_t;

static QueueHandle_t iotmd_v3_job_queue = NULL;
static QueueHandle_t iotmd_v3_event_queue = NULL;
static TaskHandle_t iotmd_v3_job_task = NULL;
static uint32_t iotmd_v3_next_job_identifier = 1;
static portMUX_TYPE iotmd_v3_job_lock = portMUX_INITIALIZER_UNLOCKED;

static void iotmd_v3_dict_store(mp_obj_t dictionary, qstr key,
    mp_obj_t value);

static void iotmd_v3_copy_text(char *target, size_t capacity,
        const char *source, size_t length) {
    size_t count = length < capacity - 1 ? length : capacity - 1;
    memcpy(target, source, count);
    target[count] = '\0';
}

static esp_err_t iotmd_v3_recovery_write(bool requested, const char *reason) {
    nvs_handle_t nvs;
    esp_err_t error = nvs_open("v3recovery", NVS_READWRITE, &nvs);
    if (error != ESP_OK) {
        return error;
    }
    if ((error = nvs_set_u8(nvs, "request", requested ? 1 : 0)) == ESP_OK &&
            (error = nvs_set_str(nvs, "reason", reason)) == ESP_OK) {
        error = nvs_commit(nvs);
    }
    nvs_close(nvs);
    return error;
}

static esp_err_t iotmd_v3_running_state(const esp_partition_t **running_out,
        esp_ota_img_states_t *state_out) {
    const esp_partition_t *running = esp_ota_get_running_partition();
    if (running == NULL) {
        return ESP_ERR_NOT_FOUND;
    }
    esp_ota_img_states_t state = ESP_OTA_IMG_UNDEFINED;
    esp_err_t error = esp_ota_get_state_partition(running, &state);
    if (error == ESP_ERR_NOT_FOUND) {
        error = ESP_OK;
    }
    if (error == ESP_OK) {
        *running_out = running;
        *state_out = state;
    }
    return error;
}

static bool iotmd_v3_label_matches(const esp_partition_t *partition,
        const char *expected) {
    return partition != NULL && strcmp(partition->label, expected) == 0;
}

static bool iotmd_v3_error_is_retryable(esp_err_t error) {
    return error == ESP_ERR_TIMEOUT || error == ESP_ERR_NO_MEM;
}

static void iotmd_v3_emit_event(const iotmd_v3_job_t *job,
        const char *status, esp_err_t error, const char *detail) {
    if (iotmd_v3_event_queue == NULL) {
        return;
    }
    iotmd_v3_event_t event;
    memset(&event, 0, sizeof(event));
    event.identifier = job->identifier;
    iotmd_v3_copy_text(
        event.kind, sizeof(event.kind), job->kind, strlen(job->kind)
    );
    iotmd_v3_copy_text(
        event.status, sizeof(event.status), status, strlen(status)
    );
    event.error = error;
    iotmd_v3_copy_text(
        event.detail, sizeof(event.detail), detail, strlen(detail)
    );
    // Diagnostics must remain bounded. Discard the oldest event rather than
    // block a native operation when the application has stopped consuming.
    if (xQueueSend(iotmd_v3_event_queue, &event, 0) != pdTRUE) {
        iotmd_v3_event_t discarded;
        xQueueReceive(iotmd_v3_event_queue, &discarded, 0);
        xQueueSend(iotmd_v3_event_queue, &event, 0);
    }
}

static esp_err_t iotmd_v3_execute_job(const iotmd_v3_job_t *job,
        const char **detail) {
    if (strcmp(job->kind, "recovery-request") == 0) {
        *detail = "native recovery requested";
        return iotmd_v3_recovery_write(true, job->argument);
    }
    const esp_partition_t *running = NULL;
    esp_ota_img_states_t state = ESP_OTA_IMG_UNDEFINED;
    esp_err_t error = iotmd_v3_running_state(&running, &state);
    if (error != ESP_OK) {
        *detail = "running partition unavailable";
        return error;
    }
    if (!iotmd_v3_label_matches(running, job->argument)) {
        *detail = "running partition changed";
        return ESP_ERR_INVALID_STATE;
    }
    if (state != ESP_OTA_IMG_PENDING_VERIFY) {
        *detail = "partition is not pending verification";
        return ESP_ERR_INVALID_STATE;
    }
    if (strcmp(job->kind, "update-confirm") == 0) {
        *detail = "native trial confirmed";
        return esp_ota_mark_app_valid_cancel_rollback();
    }
    if (strcmp(job->kind, "update-rollback") == 0) {
        if (!esp_ota_check_rollback_is_possible()) {
            *detail = "rollback partition unavailable";
            return ESP_ERR_NOT_FOUND;
        }
        // Publish intent before this successful call restarts the processor.
        iotmd_v3_emit_event(job, "restarting", ESP_OK,
            "native rollback accepted");
        *detail = "native rollback failed to restart";
        return esp_ota_mark_app_invalid_rollback_and_reboot();
    }
    *detail = "unsupported native job";
    return ESP_ERR_NOT_SUPPORTED;
}

static void iotmd_v3_job_worker(void *unused) {
    (void)unused;
    iotmd_v3_job_t job;
    while (true) {
        if (xQueueReceive(iotmd_v3_job_queue, &job, portMAX_DELAY) != pdTRUE) {
            continue;
        }
        iotmd_v3_emit_event(&job, "running", ESP_OK, "native job started");
        const char *detail = "native job completed";
        esp_err_t error = iotmd_v3_execute_job(&job, &detail);
        iotmd_v3_emit_event(
            &job, error == ESP_OK ? "completed" : "failed", error, detail
        );
    }
}

static void iotmd_v3_job_system_start(void) {
    if (iotmd_v3_job_queue != NULL && iotmd_v3_event_queue != NULL &&
            iotmd_v3_job_task != NULL) {
        return;
    }
    iotmd_v3_job_queue = xQueueCreate(
        IOTMD_V3_JOB_QUEUE_DEPTH, sizeof(iotmd_v3_job_t)
    );
    iotmd_v3_event_queue = xQueueCreate(
        IOTMD_V3_EVENT_QUEUE_DEPTH, sizeof(iotmd_v3_event_t)
    );
    if (iotmd_v3_job_queue == NULL || iotmd_v3_event_queue == NULL ||
            xTaskCreate(
                iotmd_v3_job_worker, "iotmd-v3-job",
                IOTMD_V3_JOB_STACK_BYTES, NULL, tskIDLE_PRIORITY + 1,
                &iotmd_v3_job_task
            ) != pdPASS) {
        mp_raise_msg(
            &mp_type_RuntimeError,
            MP_ERROR_TEXT("native job worker is unavailable")
        );
    }
}

static const char *iotmd_v3_ota_state_name(esp_ota_img_states_t state) {
    switch (state) {
        case ESP_OTA_IMG_NEW:
            return "new";
        case ESP_OTA_IMG_PENDING_VERIFY:
            return "pending-verify";
        case ESP_OTA_IMG_VALID:
            return "valid";
        case ESP_OTA_IMG_INVALID:
            return "invalid";
        case ESP_OTA_IMG_ABORTED:
            return "aborted";
        case ESP_OTA_IMG_UNDEFINED:
        default:
            return "undefined";
    }
}

static const esp_partition_t *iotmd_v3_running_partition(void) {
    const esp_partition_t *running = esp_ota_get_running_partition();
    if (running == NULL) {
        mp_raise_msg(
            &mp_type_RuntimeError,
            MP_ERROR_TEXT("running OTA partition is unavailable")
        );
    }
    return running;
}

static void iotmd_v3_require_running_label(const esp_partition_t *running,
        mp_obj_t expected_in) {
    size_t length = 0;
    const char *expected = mp_obj_str_get_data(expected_in, &length);
    size_t actual_length = strlen(running->label);
    if (length != actual_length ||
            memcmp(expected, running->label, actual_length) != 0) {
        mp_raise_ValueError(MP_ERROR_TEXT("running OTA partition changed"));
    }
}

static mp_obj_t iotmd_platform_v3_update_snapshot(void) {
    const esp_partition_t *running = iotmd_v3_running_partition();
    const esp_partition_t *next = esp_ota_get_next_update_partition(NULL);
    esp_ota_img_states_t state = ESP_OTA_IMG_UNDEFINED;
    esp_err_t error = esp_ota_get_state_partition(running, &state);
    if (error != ESP_OK && error != ESP_ERR_NOT_FOUND) {
        mp_raise_OSError(error);
    }
    const char *state_name = iotmd_v3_ota_state_name(state);
    mp_obj_t result = mp_obj_new_dict(6);
    iotmd_v3_dict_store(
        result, MP_QSTR_running_label,
        mp_obj_new_str(running->label, strlen(running->label))
    );
    iotmd_v3_dict_store(
        result, MP_QSTR_running_state,
        mp_obj_new_str(state_name, strlen(state_name))
    );
    iotmd_v3_dict_store(
        result, MP_QSTR_next_label,
        next == NULL ? mp_const_none :
        mp_obj_new_str(next->label, strlen(next->label))
    );
    iotmd_v3_dict_store(
        result, MP_QSTR_pending_verify,
        mp_obj_new_bool(state == ESP_OTA_IMG_PENDING_VERIFY)
    );
    iotmd_v3_dict_store(
        result, MP_QSTR_can_confirm,
        mp_obj_new_bool(state == ESP_OTA_IMG_PENDING_VERIFY)
    );
    iotmd_v3_dict_store(
        result, MP_QSTR_can_rollback,
        mp_obj_new_bool(
            state == ESP_OTA_IMG_PENDING_VERIFY &&
            esp_ota_check_rollback_is_possible()
        )
    );
    return result;
}
static MP_DEFINE_CONST_FUN_OBJ_0(
    iotmd_platform_v3_update_snapshot_obj,
    iotmd_platform_v3_update_snapshot
);

static mp_obj_t iotmd_platform_v3_update_confirm(mp_obj_t expected_in) {
    const esp_partition_t *running = iotmd_v3_running_partition();
    iotmd_v3_require_running_label(running, expected_in);
    esp_ota_img_states_t state = ESP_OTA_IMG_UNDEFINED;
    esp_err_t error = esp_ota_get_state_partition(running, &state);
    if (error != ESP_OK || state != ESP_OTA_IMG_PENDING_VERIFY) {
        mp_raise_msg(
            &mp_type_RuntimeError,
            MP_ERROR_TEXT("running OTA partition is not pending verification")
        );
    }
    error = esp_ota_mark_app_valid_cancel_rollback();
    if (error != ESP_OK) {
        mp_raise_OSError(error);
    }
    return mp_const_true;
}
static MP_DEFINE_CONST_FUN_OBJ_1(
    iotmd_platform_v3_update_confirm_obj,
    iotmd_platform_v3_update_confirm
);

static mp_obj_t iotmd_platform_v3_update_rollback(mp_obj_t expected_in) {
    const esp_partition_t *running = iotmd_v3_running_partition();
    iotmd_v3_require_running_label(running, expected_in);
    esp_ota_img_states_t state = ESP_OTA_IMG_UNDEFINED;
    esp_err_t error = esp_ota_get_state_partition(running, &state);
    if (error != ESP_OK || state != ESP_OTA_IMG_PENDING_VERIFY ||
            !esp_ota_check_rollback_is_possible()) {
        mp_raise_msg(
            &mp_type_RuntimeError,
            MP_ERROR_TEXT("running OTA partition cannot roll back")
        );
    }
    error = esp_ota_mark_app_invalid_rollback_and_reboot();
    if (error != ESP_OK) {
        mp_raise_OSError(error);
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(
    iotmd_platform_v3_update_rollback_obj,
    iotmd_platform_v3_update_rollback
);

static mp_obj_t iotmd_platform_v3_recovery_boot_begin(void) {
    nvs_handle_t nvs;
    esp_err_t error = nvs_open("v3recovery", NVS_READWRITE, &nvs);
    if (error != ESP_OK) {
        mp_raise_OSError(error);
    }
    uint32_t boots = 0;
    uint32_t failures = 0;
    uint8_t pending = 0;
    nvs_get_u32(nvs, "boots", &boots);
    nvs_get_u32(nvs, "failures", &failures);
    nvs_get_u8(nvs, "pending", &pending);
    if (pending && failures < UINT32_MAX) {
        ++failures;
    }
    if (boots < UINT32_MAX) {
        ++boots;
    }
    if ((error = nvs_set_u32(nvs, "boots", boots)) == ESP_OK &&
            (error = nvs_set_u32(nvs, "failures", failures)) == ESP_OK &&
            (error = nvs_set_u8(nvs, "pending", 1)) == ESP_OK) {
        error = nvs_commit(nvs);
    }
    nvs_close(nvs);
    if (error != ESP_OK) {
        mp_raise_OSError(error);
    }
    return mp_obj_new_int_from_uint(failures);
}
static MP_DEFINE_CONST_FUN_OBJ_0(
    iotmd_platform_v3_recovery_boot_begin_obj,
    iotmd_platform_v3_recovery_boot_begin
);

static mp_obj_t iotmd_platform_v3_recovery_snapshot(void) {
    nvs_handle_t nvs;
    esp_err_t error = nvs_open("v3recovery", NVS_READONLY, &nvs);
    uint8_t requested = 0;
    uint8_t pending = 0;
    uint32_t boots = 0;
    uint32_t failures = 0;
    char reason[IOTMD_V3_RECOVERY_REASON_BYTES + 1] = {0};
    if (error == ESP_OK) {
        size_t reason_length = sizeof(reason);
        nvs_get_u8(nvs, "request", &requested);
        nvs_get_u8(nvs, "pending", &pending);
        nvs_get_u32(nvs, "boots", &boots);
        nvs_get_u32(nvs, "failures", &failures);
        if (nvs_get_str(nvs, "reason", reason, &reason_length) != ESP_OK) {
            reason[0] = '\0';
        }
        nvs_close(nvs);
    } else if (error != ESP_ERR_NVS_NOT_FOUND) {
        mp_raise_OSError(error);
    }
    mp_obj_t result = mp_obj_new_dict(6);
    iotmd_v3_dict_store(
        result, MP_QSTR_requested, mp_obj_new_bool(requested != 0)
    );
    iotmd_v3_dict_store(
        result, MP_QSTR_reason, mp_obj_new_str(reason, strlen(reason))
    );
    iotmd_v3_dict_store(result, MP_QSTR_boot_pending,
        mp_obj_new_bool(pending != 0));
    iotmd_v3_dict_store(result, MP_QSTR_boot_count,
        mp_obj_new_int_from_uint(boots));
    iotmd_v3_dict_store(result, MP_QSTR_failed_boots,
        mp_obj_new_int_from_uint(failures));
    iotmd_v3_dict_store(result, MP_QSTR_reset_reason,
        MP_OBJ_NEW_SMALL_INT(esp_reset_reason()));
    return result;
}
static MP_DEFINE_CONST_FUN_OBJ_0(
    iotmd_platform_v3_recovery_snapshot_obj,
    iotmd_platform_v3_recovery_snapshot
);

static mp_obj_t iotmd_platform_v3_recovery_request(mp_obj_t reason_in) {
    size_t length = 0;
    const char *reason = mp_obj_str_get_data(reason_in, &length);
    if (length == 0 || length > IOTMD_V3_RECOVERY_REASON_BYTES) {
        mp_raise_ValueError(MP_ERROR_TEXT("recovery reason is invalid"));
    }
    char bounded[IOTMD_V3_RECOVERY_REASON_BYTES + 1];
    iotmd_v3_copy_text(bounded, sizeof(bounded), reason, length);
    esp_err_t error = iotmd_v3_recovery_write(true, bounded);
    if (error != ESP_OK) {
        mp_raise_OSError(error);
    }
    return mp_const_true;
}
static MP_DEFINE_CONST_FUN_OBJ_1(
    iotmd_platform_v3_recovery_request_obj,
    iotmd_platform_v3_recovery_request
);

static mp_obj_t iotmd_platform_v3_recovery_mark_healthy(void) {
    nvs_handle_t nvs;
    esp_err_t error = nvs_open("v3recovery", NVS_READWRITE, &nvs);
    if (error != ESP_OK) {
        mp_raise_OSError(error);
    }
    if ((error = nvs_set_u8(nvs, "pending", 0)) == ESP_OK &&
            (error = nvs_set_u32(nvs, "failures", 0)) == ESP_OK) {
        error = nvs_commit(nvs);
    }
    nvs_close(nvs);
    if (error != ESP_OK) {
        mp_raise_OSError(error);
    }
    return mp_const_true;
}
static MP_DEFINE_CONST_FUN_OBJ_0(
    iotmd_platform_v3_recovery_mark_healthy_obj,
    iotmd_platform_v3_recovery_mark_healthy
);

static mp_obj_t iotmd_platform_v3_recovery_clear(void) {
    esp_err_t error = iotmd_v3_recovery_write(false, "");
    if (error != ESP_OK) {
        mp_raise_OSError(error);
    }
    iotmd_platform_v3_recovery_mark_healthy();
    return mp_const_true;
}
static MP_DEFINE_CONST_FUN_OBJ_0(
    iotmd_platform_v3_recovery_clear_obj,
    iotmd_platform_v3_recovery_clear
);

static mp_obj_t iotmd_platform_v3_job_submit(mp_obj_t kind_in,
        mp_obj_t argument_in) {
    size_t kind_length = 0;
    size_t argument_length = 0;
    const char *kind = mp_obj_str_get_data(kind_in, &kind_length);
    const char *argument = mp_obj_str_get_data(
        argument_in, &argument_length
    );
    if (kind_length == 0 || kind_length > IOTMD_V3_JOB_KIND_BYTES ||
            argument_length == 0 ||
            argument_length > IOTMD_V3_JOB_ARGUMENT_BYTES) {
        mp_raise_ValueError(MP_ERROR_TEXT("native job request is invalid"));
    }
    bool supported = (
        (kind_length == sizeof("recovery-request") - 1 &&
         memcmp(kind, "recovery-request", kind_length) == 0) ||
        (kind_length == sizeof("update-confirm") - 1 &&
         memcmp(kind, "update-confirm", kind_length) == 0) ||
        (kind_length == sizeof("update-rollback") - 1 &&
         memcmp(kind, "update-rollback", kind_length) == 0)
    );
    if (!supported) {
        mp_raise_ValueError(MP_ERROR_TEXT("native job kind is unsupported"));
    }
    iotmd_v3_job_system_start();
    iotmd_v3_job_t job;
    memset(&job, 0, sizeof(job));
    portENTER_CRITICAL(&iotmd_v3_job_lock);
    job.identifier = iotmd_v3_next_job_identifier++;
    if (iotmd_v3_next_job_identifier == 0) {
        iotmd_v3_next_job_identifier = 1;
    }
    portEXIT_CRITICAL(&iotmd_v3_job_lock);
    iotmd_v3_copy_text(job.kind, sizeof(job.kind), kind, kind_length);
    iotmd_v3_copy_text(
        job.argument, sizeof(job.argument), argument, argument_length
    );
    if (xQueueSend(iotmd_v3_job_queue, &job, 0) != pdTRUE) {
        mp_raise_OSError(MP_EAGAIN);
    }
    return mp_obj_new_int_from_uint(job.identifier);
}
static MP_DEFINE_CONST_FUN_OBJ_2(
    iotmd_platform_v3_job_submit_obj,
    iotmd_platform_v3_job_submit
);

static mp_obj_t iotmd_platform_v3_event_poll(void) {
    iotmd_v3_job_system_start();
    iotmd_v3_event_t event;
    if (xQueueReceive(iotmd_v3_event_queue, &event, 0) != pdTRUE) {
        return mp_const_none;
    }
    mp_obj_t result = mp_obj_new_dict(6);
    iotmd_v3_dict_store(result, MP_QSTR_id,
        mp_obj_new_int_from_uint(event.identifier));
    iotmd_v3_dict_store(result, MP_QSTR_kind,
        mp_obj_new_str(event.kind, strlen(event.kind)));
    iotmd_v3_dict_store(result, MP_QSTR_status,
        mp_obj_new_str(event.status, strlen(event.status)));
    iotmd_v3_dict_store(result, MP_QSTR_error,
        mp_obj_new_int(event.error));
    iotmd_v3_dict_store(result, MP_QSTR_retryable,
        mp_obj_new_bool(iotmd_v3_error_is_retryable(event.error)));
    iotmd_v3_dict_store(result, MP_QSTR_detail,
        mp_obj_new_str(event.detail, strlen(event.detail)));
    return result;
}
static MP_DEFINE_CONST_FUN_OBJ_0(
    iotmd_platform_v3_event_poll_obj,
    iotmd_platform_v3_event_poll
);

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

static const char *iotmd_v3_resource_string(mp_obj_t value, size_t maximum,
        size_t *length_out) {
    size_t length = 0;
    const char *text = mp_obj_str_get_data(value, &length);
    if (length == 0 || length > maximum) {
        mp_raise_ValueError(MP_ERROR_TEXT("invalid resource string"));
    }
    for (size_t index = 0; index < length; ++index) {
        char character = text[index];
        if (!((character >= 'a' && character <= 'z') ||
                (character >= 'A' && character <= 'Z') ||
                (character >= '0' && character <= '9') ||
                character == '_' || character == '-' || character == '.' ||
                character == ':')) {
            mp_raise_ValueError(MP_ERROR_TEXT("invalid resource string"));
        }
    }
    *length_out = length;
    return text;
}

static mp_obj_t iotmd_platform_v3_resource_claim(size_t n_args,
        const mp_obj_t *args) {
    size_t kind_length = 0;
    size_t identifier_length = 0;
    size_t owner_length = 0;
    const char *kind = iotmd_v3_resource_string(
        args[0], IOTMD_V3_RESOURCE_KIND_BYTES, &kind_length
    );
    const char *identifier = iotmd_v3_resource_string(
        args[1], IOTMD_V3_RESOURCE_IDENTIFIER_BYTES, &identifier_length
    );
    const char *owner = iotmd_v3_resource_string(
        args[2], IOTMD_V3_RESOURCE_OWNER_BYTES, &owner_length
    );
    if (!((kind_length == 3 && memcmp(kind, "adc", 3) == 0) ||
            (kind_length == 4 && memcmp(kind, "gpio", 4) == 0) ||
            (kind_length == 3 && memcmp(kind, "i2c", 3) == 0) ||
            (kind_length == 3 && memcmp(kind, "spi", 3) == 0) ||
            (kind_length == 4 && memcmp(kind, "uart", 4) == 0))) {
        mp_raise_ValueError(MP_ERROR_TEXT("unsupported resource kind"));
    }
    for (size_t index = 0; index < IOTMD_V3_RESOURCE_CLAIMS; ++index) {
        iotmd_v3_resource_claim_t *claim = &iotmd_v3_resource_claims[index];
        if (claim->used && strcmp(claim->kind, kind) == 0 &&
                strcmp(claim->identifier, identifier) == 0) {
            if (strcmp(claim->owner, owner) == 0) {
                return MP_OBJ_NEW_SMALL_INT(index + 1);
            }
            mp_raise_OSError(MP_EBUSY);
        }
    }
    for (size_t index = 0; index < IOTMD_V3_RESOURCE_CLAIMS; ++index) {
        iotmd_v3_resource_claim_t *claim = &iotmd_v3_resource_claims[index];
        if (!claim->used) {
            memcpy(claim->kind, kind, kind_length);
            claim->kind[kind_length] = '\0';
            memcpy(claim->identifier, identifier, identifier_length);
            claim->identifier[identifier_length] = '\0';
            memcpy(claim->owner, owner, owner_length);
            claim->owner[owner_length] = '\0';
            claim->used = true;
            return MP_OBJ_NEW_SMALL_INT(index + 1);
        }
    }
    mp_raise_msg(
        &mp_type_RuntimeError, MP_ERROR_TEXT("resource claim limit reached")
    );
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(
    iotmd_platform_v3_resource_claim_obj, 3, 3,
    iotmd_platform_v3_resource_claim
);

static mp_obj_t iotmd_platform_v3_resource_release(mp_obj_t handle_in) {
    mp_int_t handle = mp_obj_get_int(handle_in);
    if (handle < 1 || handle > IOTMD_V3_RESOURCE_CLAIMS ||
            !iotmd_v3_resource_claims[handle - 1].used) {
        mp_raise_ValueError(MP_ERROR_TEXT("invalid resource handle"));
    }
    memset(&iotmd_v3_resource_claims[handle - 1], 0,
        sizeof(iotmd_v3_resource_claim_t));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(
    iotmd_platform_v3_resource_release_obj,
    iotmd_platform_v3_resource_release
);

static mp_obj_t iotmd_platform_v3_resource_release_owner(mp_obj_t owner_in) {
    size_t owner_length = 0;
    const char *owner = iotmd_v3_resource_string(
        owner_in, IOTMD_V3_RESOURCE_OWNER_BYTES, &owner_length
    );
    (void)owner_length;
    size_t released = 0;
    for (size_t index = 0; index < IOTMD_V3_RESOURCE_CLAIMS; ++index) {
        iotmd_v3_resource_claim_t *claim = &iotmd_v3_resource_claims[index];
        if (claim->used && strcmp(claim->owner, owner) == 0) {
            memset(claim, 0, sizeof(iotmd_v3_resource_claim_t));
            ++released;
        }
    }
    return mp_obj_new_int_from_uint(released);
}
static MP_DEFINE_CONST_FUN_OBJ_1(
    iotmd_platform_v3_resource_release_owner_obj,
    iotmd_platform_v3_resource_release_owner
);

static mp_obj_t iotmd_platform_v3_resource_snapshot(void) {
    mp_obj_t result = mp_obj_new_list(0, NULL);
    for (size_t index = 0; index < IOTMD_V3_RESOURCE_CLAIMS; ++index) {
        iotmd_v3_resource_claim_t *claim = &iotmd_v3_resource_claims[index];
        if (!claim->used) {
            continue;
        }
        mp_obj_t item = mp_obj_new_dict(4);
        iotmd_v3_dict_store(
            item, MP_QSTR_handle, MP_OBJ_NEW_SMALL_INT(index + 1)
        );
        iotmd_v3_dict_store(
            item, MP_QSTR_kind,
            mp_obj_new_str(claim->kind, strlen(claim->kind))
        );
        iotmd_v3_dict_store(
            item, MP_QSTR_identifier,
            mp_obj_new_str(claim->identifier, strlen(claim->identifier))
        );
        iotmd_v3_dict_store(
            item, MP_QSTR_owner,
            mp_obj_new_str(claim->owner, strlen(claim->owner))
        );
        mp_obj_list_append(result, item);
    }
    return result;
}
static MP_DEFINE_CONST_FUN_OBJ_0(
    iotmd_platform_v3_resource_snapshot_obj,
    iotmd_platform_v3_resource_snapshot
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

    mp_obj_t updates = mp_obj_new_dict(5);
    iotmd_v3_dict_store(updates, MP_QSTR_paired_manifest, mp_const_true);
    iotmd_v3_dict_store(updates, MP_QSTR_native_trial_observation, mp_const_true);
    iotmd_v3_dict_store(updates, MP_QSTR_native_trial_control, mp_const_true);
    // The mechanisms exist in ABI 4, but qualification remains a separate
    // physical gate. Never advertise a production claim merely because the
    // entry points compiled successfully.
    iotmd_v3_dict_store(updates, MP_QSTR_paired_trial, mp_const_false);
    iotmd_v3_dict_store(updates, MP_QSTR_native_rollback, mp_const_false);

    mp_obj_t recovery = mp_obj_new_dict(4);
    iotmd_v3_dict_store(recovery, MP_QSTR_native_state, mp_const_true);
    iotmd_v3_dict_store(recovery, MP_QSTR_product_independent, mp_const_true);
    iotmd_v3_dict_store(recovery, MP_QSTR_signed_release, mp_const_true);
    iotmd_v3_dict_store(recovery, MP_QSTR_qualified, mp_const_false);

    mp_obj_t jobs = mp_obj_new_dict(5);
    iotmd_v3_dict_store(jobs, MP_QSTR_async_worker, mp_const_true);
    iotmd_v3_dict_store(jobs, MP_QSTR_max_pending,
        MP_OBJ_NEW_SMALL_INT(IOTMD_V3_JOB_QUEUE_DEPTH));
    iotmd_v3_dict_store(jobs, MP_QSTR_max_events,
        MP_OBJ_NEW_SMALL_INT(IOTMD_V3_EVENT_QUEUE_DEPTH));
    iotmd_v3_dict_store(jobs, MP_QSTR_timeout_ms,
        MP_OBJ_NEW_SMALL_INT(IOTMD_V3_JOB_TIMEOUT_MS));
    iotmd_v3_dict_store(jobs, MP_QSTR_qualified, mp_const_false);

    mp_obj_t resource_kinds_items[] = {
        mp_obj_new_str("adc", sizeof("adc") - 1),
        mp_obj_new_str("gpio", sizeof("gpio") - 1),
        mp_obj_new_str("i2c", sizeof("i2c") - 1),
        mp_obj_new_str("spi", sizeof("spi") - 1),
        mp_obj_new_str("uart", sizeof("uart") - 1),
    };
    mp_obj_t resources = mp_obj_new_dict(3);
    iotmd_v3_dict_store(resources, MP_QSTR_managed, mp_const_true);
    iotmd_v3_dict_store(
        resources, MP_QSTR_max_claims,
        MP_OBJ_NEW_SMALL_INT(IOTMD_V3_RESOURCE_CLAIMS)
    );
    iotmd_v3_dict_store(
        resources, MP_QSTR_kinds,
        mp_obj_new_tuple(
            MP_ARRAY_SIZE(resource_kinds_items), resource_kinds_items
        )
    );

    mp_obj_t result = mp_obj_new_dict(11);
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
    iotmd_v3_dict_store(result, MP_QSTR_recovery, recovery);
    iotmd_v3_dict_store(result, MP_QSTR_jobs, jobs);
    iotmd_v3_dict_store(result, MP_QSTR_resources, resources);
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
    { MP_ROM_QSTR(MP_QSTR_resource_claim),
      MP_ROM_PTR(&iotmd_platform_v3_resource_claim_obj) },
    { MP_ROM_QSTR(MP_QSTR_resource_release),
      MP_ROM_PTR(&iotmd_platform_v3_resource_release_obj) },
    { MP_ROM_QSTR(MP_QSTR_resource_release_owner),
      MP_ROM_PTR(&iotmd_platform_v3_resource_release_owner_obj) },
    { MP_ROM_QSTR(MP_QSTR_resource_snapshot),
      MP_ROM_PTR(&iotmd_platform_v3_resource_snapshot_obj) },
    { MP_ROM_QSTR(MP_QSTR_update_snapshot),
      MP_ROM_PTR(&iotmd_platform_v3_update_snapshot_obj) },
    { MP_ROM_QSTR(MP_QSTR_update_confirm),
      MP_ROM_PTR(&iotmd_platform_v3_update_confirm_obj) },
    { MP_ROM_QSTR(MP_QSTR_update_rollback),
      MP_ROM_PTR(&iotmd_platform_v3_update_rollback_obj) },
    { MP_ROM_QSTR(MP_QSTR_recovery_boot_begin),
      MP_ROM_PTR(&iotmd_platform_v3_recovery_boot_begin_obj) },
    { MP_ROM_QSTR(MP_QSTR_recovery_snapshot),
      MP_ROM_PTR(&iotmd_platform_v3_recovery_snapshot_obj) },
    { MP_ROM_QSTR(MP_QSTR_recovery_request),
      MP_ROM_PTR(&iotmd_platform_v3_recovery_request_obj) },
    { MP_ROM_QSTR(MP_QSTR_recovery_mark_healthy),
      MP_ROM_PTR(&iotmd_platform_v3_recovery_mark_healthy_obj) },
    { MP_ROM_QSTR(MP_QSTR_recovery_clear),
      MP_ROM_PTR(&iotmd_platform_v3_recovery_clear_obj) },
    { MP_ROM_QSTR(MP_QSTR_job_submit),
      MP_ROM_PTR(&iotmd_platform_v3_job_submit_obj) },
    { MP_ROM_QSTR(MP_QSTR_event_poll),
      MP_ROM_PTR(&iotmd_platform_v3_event_poll_obj) },
};
static MP_DEFINE_CONST_DICT(
    iotmd_platform_v3_module_globals,
    iotmd_platform_v3_module_globals_table
);

const mp_obj_module_t iotmd_platform_v3_user_cmodule = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&iotmd_platform_v3_module_globals,
};

// Keep the registration on one line: MicroPython's module-definition scanner
// discovers this source declaration before the C compiler handles it.
MP_REGISTER_MODULE(MP_QSTR__iotmd_platform_v3, iotmd_platform_v3_user_cmodule);
