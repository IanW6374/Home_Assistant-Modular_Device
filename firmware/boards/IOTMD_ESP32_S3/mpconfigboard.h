#define MICROPY_HW_BOARD_NAME               "IoT-MD ESP32-S3 OTA"
#define MICROPY_HW_MCU_NAME                 "ESP32S3"
#define MICROPY_HW_ENABLE_UART_REPL         (1)

// MicroPython 1.29's generic USB NCM implementation is not yet integrated with
// the ESP32 port's network locking and NIC registration APIs. Keep the board
// capability disabled until that port is qualified; application support is
// capability-gated and remains available for a future compatible core.
#define MICROPY_PY_NETWORK_USBD_NCM         (0)
#define MICROPY_PY_BLUETOOTH                (0)
#define MICROPY_HW_I2C0_SCL                 (9)
#define MICROPY_HW_I2C0_SDA                 (8)
