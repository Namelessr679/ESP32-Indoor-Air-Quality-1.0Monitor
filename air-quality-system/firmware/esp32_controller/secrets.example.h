#pragma once
// Copy to secrets.h. Never commit credentials.
#define WIFI_SSID "YOUR_WIFI_NAME"
#define WIFI_PASSWORD "YOUR_WIFI_PASSWORD"
#define FAN_API_KEY "CHANGE_ME"
// REQUIRED: define FAN_PIN after checking your board and fan driver.
// Existing LCD uses 4, 5, 18, 19, 23, 25; SCD41 uses 21, 22.
// #define FAN_PIN your_verified_output_gpio
#ifndef FAN_PIN
#error "Set FAN_PIN in secrets.h to a verified free output GPIO"
#endif
#define FAN_ACTIVE_HIGH true
