# Edge-Based Indoor Air Quality Monitor (ESP32)

An ESP32-based edge device that measures indoor CO₂, temperature, and humidity in real time using the **Sensirion SCD41** sensor, displays readings on a **16×2 LCD**, and serves live data over **Wi-Fi** via a built-in HTTP web server.

---

## Features

- **Real-time sensing** — CO₂ (ppm), temperature (°C), and relative humidity (%) via SCD41 over I²C
- **16×2 LCD display** — Shows current readings locally without any additional device
- **Wi-Fi connectivity** — Connects to a Wi-Fi hotspot and serves data over HTTP
- **Web dashboard** — Human-readable HTML page at `http://esp32.local/`
- **JSON API endpoint** — Machine-readable data at `http://esp32.local/json` for integration with other systems
- **mDNS support** — Access the device by hostname (`esp32.local`) instead of IP address
- **Auto-reconnect** — Automatically re-establishes Wi-Fi and mDNS if the connection drops

---

## Hardware

| Component | Details |
|-----------|---------|
| Microcontroller | ESP32 (any standard dev board) |
| CO₂ / Temp / RH sensor | Sensirion SCD41 (I²C, address `0x62`) |
| Display | 16×2 character LCD (4-bit parallel interface) |

### Pin Connections

#### LCD (4-bit parallel)
| LCD Pin | ESP32 GPIO |
|---------|-----------|
| RS | 4 |
| E | 5 |
| D4 | 18 |
| D5 | 19 |
| D6 | 23 |
| D7 | 25 |

#### SCD41 (I²C)
| SCD41 Pin | ESP32 |
|-----------|-------|
| SDA | GPIO 21 (default) |
| SCL | GPIO 22 (default) |

---

## Software Dependencies

Install the following libraries via the **Arduino Library Manager**:

| Library | Purpose |
|---------|---------|
| `SensirionI2cScd4x` | SCD41 sensor driver |
| `LiquidCrystal` | 16×2 LCD driver |
| `WiFi` | Built-in ESP32 Wi-Fi |
| `WebServer` | Built-in HTTP server |
| `ESPmDNS` | mDNS hostname resolution |

---

## Setup

1. Open `ESP32.ino` in the **Arduino IDE** (or VS Code with the Arduino extension).
2. Set your Wi-Fi credentials in the source file:
   ```cpp
   const char* ssid     = "YOUR_SSID";
   const char* password = "YOUR_PASSWORD";
   ```
3. Select your ESP32 board and COM port, then upload.

---

## Usage

Once running:

| URL | Description |
|-----|-------------|
| `http://esp32.local/` | HTML dashboard with live sensor readings |
| `http://esp32.local/json` | JSON endpoint for automation / logging |

Example JSON response:
```json
{
  "co2": 842,
  "temp_c": 23.45,
  "rh": 48.20,
  "device_ip": "192.168.1.42",
  "mdns": "esp32.local",
  "time_ms": 34521
}
```

---

## Project Context

This project is part of **Edge-Based Indoor Air Quality Prediction and Ventilation Control** research, where the ESP32 acts as a low-cost edge node for collecting environmental data that can drive automated ventilation decisions.

---

## License

MIT License — feel free to use, modify, and distribute.
