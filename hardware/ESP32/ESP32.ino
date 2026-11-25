#include <Wire.h>
#include <ArduinoJson.h>  // Fan command JSON (ArduinoJson 7.x)
#include <WiFi.h>
#include <WebServer.h>
#include <ESPmDNS.h>
#include <SensirionI2cScd4x.h>
#include <LiquidCrystal.h>

// LCD: RS, E, D4, D5, D6, D7
// Move LCD D7 from GPIO 25 to GPIO 27 before connecting the fan.
LiquidCrystal lcd(4, 5, 18, 19, 23, 27);

// ===== WiFi setting =====
#if __has_include("secrets.h")
#include "secrets.h"
#else
const char* ssid = "YOUR_SSID";
const char* password = "YOUR_PASSWORD";
const char* FAN_API_KEY = "CHANGE_ME";
#endif

bool wifiConnected = false;

SensirionI2cScd4x scd4x;
static const uint8_t SCD4X_I2C_ADDR = 0x62;

unsigned long lastLcdUpdate = 0;
unsigned long lastWifiPrint = 0;

// ===== Web server (HTTP) =====
WebServer server(80);

// ===== Fan control: configure these for your board and driver =====
const int FAN_INA_PIN = 25;
const int FAN_INB_PIN = 26;
bool fanOn = false;
unsigned long lastFanCommandMs = 0;
const unsigned long FAN_LEASE_MS = 30000;

void applyFan(bool on, const char* reason) {
  // INB stays LOW for both tested states; never reverse the motor.
  digitalWrite(FAN_INB_PIN, LOW);
  digitalWrite(FAN_INA_PIN, on ? HIGH : LOW);
  if (fanOn != on) {
    Serial.printf("[Fan] %s (%s)\n", on ? "ON" : "OFF", reason);
  }
  fanOn = on;
}

void handleFan() {
  if (String(FAN_API_KEY).length() < 16 || server.header("X-API-Key") != FAN_API_KEY) {
    server.send(401, "application/json", "{\"error\":\"unauthorized\"}");
    return;
  }
  if (server.method() == HTTP_POST) {
    JsonDocument command;
    if (server.arg("plain").length() > 128 ||
        deserializeJson(command, server.arg("plain")) ||
        !command["state"].is<const char*>()) {
      server.send(400, "application/json", "{\"error\":\"invalid state\"}");
      return;
    }
    String state = command["state"].as<const char*>();
    if (state != "on" && state != "off") {
      server.send(400, "application/json", "{\"error\":\"use on or off\"}");
      return;
    }
    applyFan(state == "on", "HTTP command");
    lastFanCommandMs = millis();
  }
  String reply = String("{\"state\":\"") + (fanOn ? "on" : "off") + "\",\"lease_ms\":30000";
  if (server.method() == HTTP_POST) reply += ",\"command_applied\":true";
  server.send(200, "application/json", reply + "}");
}


// latest sensor values to serve on website
volatile uint16_t lastCo2 = 0;
volatile float lastT = 0.0f;
volatile float lastRh = 0.0f;
volatile unsigned long lastSensorMs = 0;
unsigned long lastSensorCheckMs = 0;
unsigned long lastSensorWaitLogMs = 0;
const unsigned long SENSOR_STALE_MS = 15000;

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
  if (lastSensorMs == 0 || (unsigned long)(millis() - lastSensorMs) > SENSOR_STALE_MS) {
    server.send(503, "application/json", "{\"error\":\"sensor reading unavailable or stale\"}");
    return;
  }
  String json = "{";
  json += "\"co2\":" + String(lastCo2) + ",";
  json += "\"temp_c\":" + String(lastT, 2) + ",";
  json += "\"rh\":" + String(lastRh, 2) + ",";
  json += "\"device_ip\":\"" + WiFi.localIP().toString() + "\",";
  json += "\"mdns\":\"esp32.local\",";
  json += "\"sensor_age_ms\":" + String(millis() - lastSensorMs) + ",";
  json += "\"time_ms\":" + String(millis());
  json += "}";
  server.send(200, "application/json", json);
}

// -------------------- WiFi helpers --------------------
unsigned long lastWifiAttemptMs = 0;
const unsigned long WIFI_RETRY_MS = 10000;

void setupWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(ssid, password);
  lastWifiAttemptMs = millis();
  Serial.println("[WiFi] Connecting asynchronously");
}

void checkWifiStatus() {
  if (WiFi.status() == WL_CONNECTED) {
    if (!wifiConnected) {
      wifiConnected = true;
      Serial.print("[WiFi] Connected: ");
      Serial.println(WiFi.localIP());
      MDNS.end();
      if (!MDNS.begin("esp32")) Serial.println("[mDNS] Start failed");
    }
    return;
  }
  applyFan(false, "WiFi disconnected");
  if (wifiConnected) {
    wifiConnected = false;
    Serial.println("[WiFi] Lost connection");
  }
  if ((unsigned long)(millis() - lastWifiAttemptMs) >= WIFI_RETRY_MS) {
    lastWifiAttemptMs = millis();
    Serial.println("[WiFi] Retrying connection");
    WiFi.reconnect();
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
  // SCD41 updates about every five seconds; avoid hammering I2C on every loop.
  if ((unsigned long)(millis() - lastSensorCheckMs) < 1000) return;
  lastSensorCheckMs = millis();
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

  if (!isDataReady) {
    if ((unsigned long)(millis() - lastSensorWaitLogMs) >= SENSOR_STALE_MS) {
      lastSensorWaitLogMs = millis();
      Serial.println("[SCD41] Waiting for a new measurement");
    }
    return;
  }

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

  if (co2 == 0) {
    Serial.println("[SCD41] Discarded zero CO2 measurement");
    return;
  }

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
  // Set output latches LOW before enabling outputs, before any startup work.
  digitalWrite(FAN_INA_PIN, LOW);
  digitalWrite(FAN_INB_PIN, LOW);
  pinMode(FAN_INA_PIN, OUTPUT);
  pinMode(FAN_INB_PIN, OUTPUT);
  Serial.begin(115200);
  Serial.println("[Fan] OFF (startup)");

  lcd.begin(16, 2);
  lcd.clear();
  lcd.print("Booting...");

  setupWifi();

  const char* fanHeaders[] = {"X-API-Key"};
  server.collectHeaders(fanHeaders, 1);
  server.on("/fan", HTTP_GET, handleFan);
  server.on("/fan", HTTP_POST, handleFan);
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
  if (fanOn && (unsigned long)(millis() - lastFanCommandMs) >= FAN_LEASE_MS) {
    applyFan(false, "command lease expired");
  }
  checkWifiStatus();
  if (wifiConnected) server.handleClient();
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
