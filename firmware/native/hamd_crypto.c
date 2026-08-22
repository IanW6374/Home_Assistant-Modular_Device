// Native cryptographic primitives required by HAMD firmware.

#include "py/obj.h"
#include "py/runtime.h"

#include "mbedtls/md.h"
#include "mbedtls/gcm.h"
#include "mbedtls/pkcs5.h"
#include "mbedtls/platform_util.h"

#define HAMD_PBKDF2_DIGEST_BYTES (32)
#define HAMD_PBKDF2_MAX_INPUT_BYTES (1024)
#define HAMD_PBKDF2_MAX_ITERATIONS (1000000)

static mp_obj_t hamd_crypto_pbkdf2_sha256(mp_obj_t password_obj,
    mp_obj_t salt_obj, mp_obj_t iterations_obj) {
    mp_buffer_info_t password;
    mp_buffer_info_t salt;
    mp_get_buffer_raise(password_obj, &password, MP_BUFFER_READ);
    mp_get_buffer_raise(salt_obj, &salt, MP_BUFFER_READ);

    if (password.len > HAMD_PBKDF2_MAX_INPUT_BYTES ||
        salt.len == 0 || salt.len > HAMD_PBKDF2_MAX_INPUT_BYTES) {
        mp_raise_ValueError(MP_ERROR_TEXT("PBKDF2 input is too large"));
    }

    mp_int_t iterations = mp_obj_get_int(iterations_obj);
    if (iterations < 1 || iterations > HAMD_PBKDF2_MAX_ITERATIONS) {
        mp_raise_ValueError(MP_ERROR_TEXT("PBKDF2 iteration count is out of range"));
    }

    unsigned char output[HAMD_PBKDF2_DIGEST_BYTES];
    int result = mbedtls_pkcs5_pbkdf2_hmac_ext(
        MBEDTLS_MD_SHA256,
        (const unsigned char *)password.buf,
        password.len,
        (const unsigned char *)salt.buf,
        salt.len,
        (unsigned int)iterations,
        HAMD_PBKDF2_DIGEST_BYTES,
        output
    );
    if (result != 0) {
        mbedtls_platform_zeroize(output, sizeof(output));
        mp_raise_msg_varg(
            &mp_type_RuntimeError,
            MP_ERROR_TEXT("native PBKDF2 failed (%d)"),
            result
        );
    }

    mp_obj_t derived_key = mp_obj_new_bytes(output, sizeof(output));
    mbedtls_platform_zeroize(output, sizeof(output));
    return derived_key;
}
static MP_DEFINE_CONST_FUN_OBJ_3(
    hamd_crypto_pbkdf2_sha256_obj,
    hamd_crypto_pbkdf2_sha256
);

#define HAMD_AES_KEY_BYTES (32)
#define HAMD_GCM_NONCE_BYTES (12)
#define HAMD_GCM_TAG_BYTES (16)
#define HAMD_GCM_MAX_PAYLOAD_BYTES (131072)

static mp_obj_t hamd_crypto_aes_gcm_encrypt(size_t n_args,
    const mp_obj_t *args) {
    mp_buffer_info_t key;
    mp_buffer_info_t nonce;
    mp_buffer_info_t input;
    mp_buffer_info_t aad;
    mp_get_buffer_raise(args[0], &key, MP_BUFFER_READ);
    mp_get_buffer_raise(args[1], &nonce, MP_BUFFER_READ);
    mp_get_buffer_raise(args[2], &input, MP_BUFFER_READ);
    mp_get_buffer_raise(args[3], &aad, MP_BUFFER_READ);
    if (key.len != HAMD_AES_KEY_BYTES || nonce.len != HAMD_GCM_NONCE_BYTES ||
        input.len > HAMD_GCM_MAX_PAYLOAD_BYTES) {
        mp_raise_ValueError(MP_ERROR_TEXT("AES-GCM parameters are invalid"));
    }
    vstr_t output;
    vstr_init_len(&output, input.len + HAMD_GCM_TAG_BYTES);
    mbedtls_gcm_context context;
    mbedtls_gcm_init(&context);
    int result = mbedtls_gcm_setkey(
        &context, MBEDTLS_CIPHER_ID_AES, key.buf, HAMD_AES_KEY_BYTES * 8
    );
    if (result == 0) {
        result = mbedtls_gcm_crypt_and_tag(
            &context, MBEDTLS_GCM_ENCRYPT, input.len,
            nonce.buf, nonce.len, aad.buf, aad.len, input.buf,
            (unsigned char *)output.buf, HAMD_GCM_TAG_BYTES,
            (unsigned char *)output.buf + input.len
        );
    }
    mbedtls_gcm_free(&context);
    if (result != 0) {
        mbedtls_platform_zeroize(output.buf, output.len);
        vstr_clear(&output);
        mp_raise_msg_varg(
            &mp_type_RuntimeError,
            MP_ERROR_TEXT("native AES-GCM encryption failed (%d)"), result
        );
    }
    return mp_obj_new_bytes_from_vstr(&output);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(
    hamd_crypto_aes_gcm_encrypt_obj, 4, 4, hamd_crypto_aes_gcm_encrypt
);

static mp_obj_t hamd_crypto_aes_gcm_decrypt(size_t n_args,
    const mp_obj_t *args) {
    mp_buffer_info_t key;
    mp_buffer_info_t nonce;
    mp_buffer_info_t input;
    mp_buffer_info_t aad;
    mp_get_buffer_raise(args[0], &key, MP_BUFFER_READ);
    mp_get_buffer_raise(args[1], &nonce, MP_BUFFER_READ);
    mp_get_buffer_raise(args[2], &input, MP_BUFFER_READ);
    mp_get_buffer_raise(args[3], &aad, MP_BUFFER_READ);
    if (key.len != HAMD_AES_KEY_BYTES || nonce.len != HAMD_GCM_NONCE_BYTES ||
        input.len < HAMD_GCM_TAG_BYTES ||
        input.len > HAMD_GCM_MAX_PAYLOAD_BYTES + HAMD_GCM_TAG_BYTES) {
        mp_raise_ValueError(MP_ERROR_TEXT("AES-GCM parameters are invalid"));
    }
    size_t plaintext_len = input.len - HAMD_GCM_TAG_BYTES;
    vstr_t output;
    vstr_init_len(&output, plaintext_len);
    mbedtls_gcm_context context;
    mbedtls_gcm_init(&context);
    int result = mbedtls_gcm_setkey(
        &context, MBEDTLS_CIPHER_ID_AES, key.buf, HAMD_AES_KEY_BYTES * 8
    );
    if (result == 0) {
        result = mbedtls_gcm_auth_decrypt(
            &context, plaintext_len, nonce.buf, nonce.len,
            aad.buf, aad.len,
            (const unsigned char *)input.buf + plaintext_len,
            HAMD_GCM_TAG_BYTES, input.buf,
            (unsigned char *)output.buf
        );
    }
    mbedtls_gcm_free(&context);
    if (result != 0) {
        mbedtls_platform_zeroize(output.buf, output.len);
        vstr_clear(&output);
        mp_raise_ValueError(MP_ERROR_TEXT("AES-GCM authentication failed"));
    }
    return mp_obj_new_bytes_from_vstr(&output);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(
    hamd_crypto_aes_gcm_decrypt_obj, 4, 4, hamd_crypto_aes_gcm_decrypt
);

static const mp_rom_map_elem_t hamd_crypto_module_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR__hamd_crypto) },
    { MP_ROM_QSTR(MP_QSTR_pbkdf2_sha256),
      MP_ROM_PTR(&hamd_crypto_pbkdf2_sha256_obj) },
    { MP_ROM_QSTR(MP_QSTR_aes_gcm_encrypt),
      MP_ROM_PTR(&hamd_crypto_aes_gcm_encrypt_obj) },
    { MP_ROM_QSTR(MP_QSTR_aes_gcm_decrypt),
      MP_ROM_PTR(&hamd_crypto_aes_gcm_decrypt_obj) },
};
static MP_DEFINE_CONST_DICT(
    hamd_crypto_module_globals,
    hamd_crypto_module_globals_table
);

const mp_obj_module_t hamd_crypto_user_cmodule = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&hamd_crypto_module_globals,
};

MP_REGISTER_MODULE(MP_QSTR__hamd_crypto, hamd_crypto_user_cmodule);
