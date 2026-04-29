#include <Wire.h>
#include <WiFi.h>
#include <WebServer.h>
#include <ESPmDNS.h>
#include <SensirionI2cScd4x.h>
#include <LiquidCrystal.h>

// LCD: RS, E, D4, D5, D6, D7
LiquidCrystal lcd(4, 5, 18, 19, 23, 25);

// ===== WiFi setting =====
const char* ssid = // Your hotspot ID;
const char* password = // Your hotspot password;

bool wifiConnected = false;

SensirionI2cScd4x scd4x;
static const uint8_t SCD4X_I2C_ADDR = 0x62;

unsigned long lastLcdUpdate = 0;
unsigned long lastWifiPrint = 0;

// ===== Web server (HTTP) =====
WebServer server(80);

// latest sensor values to serve on website
volatile uint16_t lastCo2 = 0;
volatile float lastT = 0.0f;
volatile float lastRh = 0.0f;
volatile unsigned long lastSensorMs = 0;

// -------------------- Web handlers --------------------
String htmlPage() {
  String ip = WiFi.isConnected() ? WiFi.localIP().toString() : "Not connected";

  String html = "<!DOCTYPE html><html><head><meta charset='utf-8'>";
  html += "<meta name='viewport' content='width=device-width, initial-scale=1.0'>";
  html += "<title>ESP32 Air Monitor</title></head><body>";
  html += "<h1>ESP32 Air Quality Monitor</h1>";
  html += "<p><b>CO2:</b> " + String(lastCo2) + " ppm</p>";
  html += "<p><b>Temperature:</b> " + String(lastT, 2) + " C</p>";
  html += "<p><b>Humidity:</b> " + String(lastRh, 2) + " %</p>";
  html += "<p><b>IP:</b> " + ip + "</p>";
  html += "<p><b>mDNS:</b> http://esp32.local/</p>";
  html += "<p><b>JSON:</b> <a href='/json'>/json</a></p>";
  html += "</body></html>";
  return html;
}

void handleRoot() {
  server.send(200, "text/html", htmlPage());
}

void handleJson() {
  String json = "{";
  json += "\"co2\":" + String(lastCo2) + ",";
  json += "\"temp_c\":" + String(lastT, 2) + ",";
  json += "\"rh\":" + String(lastRh, 2) + ",";
  json += "\"device_ip\":\"" + WiFi.localIP().toString() + "\",";
  json += "\"mdns\":\"esp32.local\",";
  json += "\"time_ms\":" + String(millis());
  json += "}";
  server.send(200, "application/json", json);
}

// -------------------- WiFi helpers --------------------
void setupWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.disconnect(true);
  delay(200);

  Serial.println("\n[WiFi] Scanning networks...");
  int n = WiFi.scanNetworks();
  if (n <= 0) {
    Serial.println("[WiFi] No networks found");
  } else {
    for (int i = 0; i < n; i++) {
      Serial.print("  - ");
      Serial.print(WiFi.SSID(i));
      Serial.print(" (RSSI ");
      Serial.print(WiFi.RSSI(i));
      Serial.println(")");
    }
  }

  Serial.print("\n[WiFi] Connecting to: ");
  Serial.println(ssid);

  lcd.clear();
  lcd.print("WiFi Connecting");

  WiFi.begin(ssid, password);

  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
    Serial.print(" status=");
    Serial.println((int)WiFi.status());

    if (millis() - start > 20000) {
      Serial.println("\n[WiFi] FAILED (timeout)");
      Serial.print("[WiFi] Final status=");
      Serial.println((int)WiFi.status());

      wifiConnected = false;

      lcd.clear();
      lcd.print("WiFi Failed");
      return;
    }
  }

  wifiConnected = true;

  Serial.println("\n[WiFi] CONNECTED ✅");
  Serial.print("[WiFi] DHCP IP: ");
  Serial.println(WiFi.localIP());
  Serial.print("[WiFi] Gateway: ");
  Serial.println(WiFi.gatewayIP());
  Serial.print("[WiFi] RSSI: ");
  Serial.println(WiFi.RSSI());

  lcd.clear();
  lcd.print("WiFi OK");
  lcd.setCursor(0, 1);
  lcd.print(WiFi.localIP());
}

void startMDNS() {
  if (WiFi.status() == WL_CONNECTED) {
    if (MDNS.begin("esp32")) {
      Serial.println("[mDNS] Started: http://esp32.local");
    } else {
      Serial.println("[mDNS] Failed to start");
    }
  }
}

void checkWifiStatus() {
  if (WiFi.status() != WL_CONNECTED) {
    if (wifiConnected) {
      Serial.println("[WiFi] LOST CONNECTION");
      wifiConnected = false;

      lcd.clear();
      lcd.print("WiFi Lost");
    }

    WiFi.disconnect(true);
    delay(500);

    Serial.println("[WiFi] Reconnecting...");
    WiFi.begin(ssid, password);

    unsigned long start = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - start < 10000) {
      delay(500);
      Serial.print("#");
    }

    if (WiFi.status() == WL_CONNECTED) {
      wifiConnected = true;
      Serial.println("\n[WiFi] RECONNECTED ✅");
      Serial.print("[WiFi] DHCP IP: ");
      Serial.println(WiFi.localIP());
      Serial.print("[WiFi] Gateway: ");
      Serial.println(WiFi.gatewayIP());

      MDNS.end();
      if (!MDNS.begin("esp32")) {
        Serial.println("[mDNS] Restart failed");
      } else {
        Serial.println("[mDNS] Restarted: http://esp32.local");
      }

      lcd.clear();
      lcd.print("WiFi Reconnected");
      lcd.setCursor(0, 1);
      lcd.print(WiFi.localIP());
    } else {
      Serial.println("\n[WiFi] Reconnect failed");
    }
  }
}

// -------------------- Sensor setup --------------------
void setupSensor() {
  Wire.begin();
  scd4x.begin(Wire, SCD4X_I2C_ADDR);

  uint16_t error;
  char errorMessage[256];

  error = scd4x.stopPeriodicMeasurement();
  if (error) {
    Serial.print("Error stopping measurement: ");
    errorToString(error, errorMessage, sizeof(errorMessage));
    Serial.println(errorMessage);
  }

  delay(500);

  error = scd4x.startPeriodicMeasurement();
  if (error) {
    Serial.print("Error starting measurement: ");
    errorToString(error, errorMessage, sizeof(errorMessage));
    Serial.println(errorMessage);
  } else {
    Serial.println("[SCD41] Started periodic measurement");
  }
}

// -------------------- Read sensor --------------------
void readSensor() {
  uint16_t error;
  char errorMessage[256];

  bool isDataReady = false;
  error = scd4x.getDataReadyStatus(isDataReady);
  if (error) {
    Serial.print("Error checking data ready: ");
    errorToString(error, errorMessage, sizeof(errorMessage));
    Serial.println(errorMessage);
    return;
  }

  if (!isDataReady) return;

  uint16_t co2 = 0;
  float temperature = 0.0f;
  float humidity = 0.0f;

  error = scd4x.readMeasurement(co2, temperature, humidity);
  if (error) {
    Serial.print("Error reading measurement: ");
    errorToString(error, errorMessage, sizeof(errorMessage));
    Serial.println(errorMessage);
    return;
  }

  if (co2 == 0) return;

  lastCo2 = co2;
  lastT = temperature;
  lastRh = humidity;
  lastSensorMs = millis();

  Serial.print("CO2: ");
  Serial.print(lastCo2);
  Serial.print(" ppm | T: ");
  Serial.print(lastT, 2);
  Serial.print(" C | RH: ");
  Serial.print(lastRh, 2);
  Serial.println(" %");
}

// -------------------- LCD update --------------------
void updateLCD() {
  if (millis() - lastLcdUpdate < 2000) return;
  lastLcdUpdate = millis();

  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("CO2:");
  lcd.print(lastCo2);
  lcd.print("ppm");

  lcd.setCursor(0, 1);
  lcd.print(lastT, 1);
  lcd.print("C ");
  lcd.print(lastRh, 0);
  lcd.print("%");
}

// -------------------- setup --------------------
void setup() {
  Serial.begin(115200);
  delay(300);

  lcd.begin(16, 2);
  lcd.clear();
  lcd.print("Booting...");

  setupWifi();
  startMDNS();

  server.on("/", handleRoot);
  server.on("/json", handleJson);
  server.begin();

  Serial.println("[HTTP] Web server started on port 80");
  Serial.println("[HTTP] Open: http://esp32.local/");
  Serial.println("[HTTP] JSON: http://esp32.local/json");
  Serial.print("[HTTP] Direct IP: http://");
  Serial.print(WiFi.localIP());
  Serial.println("/json");

  setupSensor();
}

// -------------------- loop --------------------
void loop() {
  server.handleClient();
  checkWifiStatus();
  readSensor();
  updateLCD();

  if (millis() - lastWifiPrint > 10000) {
    lastWifiPrint = millis();
    Serial.print("[WiFi] Status: ");
    Serial.print(WiFi.status() == WL_CONNECTED ? "CONNECTED" : "DISCONNECTED");
    Serial.print(" | IP: ");
    Serial.print(WiFi.localIP());
    Serial.print(" | RSSI: ");
    Serial.println(WiFi.RSSI());
  }
}