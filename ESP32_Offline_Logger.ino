#include <Arduino.h>
#include <Wire.h>
#include <LittleFS.h>
#include <SensirionI2cScd4x.h>
#include <LiquidCrystal.h>

SensirionI2cScd4x sensor;
LiquidCrystal lcd(4, 5, 18, 19, 23, 25);
File recordingFile;

constexpr int SDA_PIN = 21;
constexpr int SCL_PIN = 22;
constexpr uint32_t RECORD_INTERVAL_MS = 10000;
constexpr size_t MIN_FREE_BYTES = 128;

bool storageOK = false;
bool sensorOK = false;
bool recording = false;
String currentFilename;
String commandBuffer;
uint32_t sessionStartMs = 0;
uint32_t lastCheckMs = 0;
uint32_t rowsWritten = 0;
bool hasReading = false;
uint16_t lastCo2 = 0;
float lastTemperature = 0;
float lastHumidity = 0;

void lcdLine(uint8_t row, String message) {
  if (message.length() > 16) message.remove(16);
  lcd.setCursor(0, row);
  lcd.print(message);
  for (int i = message.length(); i < 16; ++i) lcd.print(' ');
}

void updateLCD() {
  String status = recording ? "REC" : "STOP";
  if (!sensorOK) {
    lcdLine(0, "SCD41 ERROR");
  } else if (!hasReading) {
    lcdLine(0, "CO2: WAIT   " + status);
  } else {
    lcdLine(0, "CO2:" + String(lastCo2) + "ppm " + status);
  }

  if (!storageOK) {
    lcdLine(1, "STORAGE ERROR");
    return;
  }
  if (!hasReading) {
    lcdLine(1, "Waiting for data");
    return;
  }
  String session = "---";
  if (currentFilename.length() >= 15) {
    session = currentFilename.substring(9, 15);
    session = session.substring(3);
  }
  lcdLine(1, String(lastTemperature, 1) + "C " +
             String(lastHumidity, 0) + "%  #" + session);
}

String sessionPath(const String& name) {
  if (name.length() != 18 || !name.startsWith("session_") || !name.endsWith(".csv")) return "";
  for (int i = 8; i < 14; ++i) {
    if (name[i] < '0' || name[i] > '9') return "";
  }
  return "/" + name;
}

String nextSessionPath() {
  char name[32];
  for (unsigned long n = 1; n <= 999999; ++n) {
    snprintf(name, sizeof(name), "/session_%06lu.csv", n);
    if (!LittleFS.exists(name)) return String(name);
  }
  return "";
}

void stopRecording() {
  if (!recording) {
    Serial.println("NOT_RECORDING");
    return;
  }
  recording = false;
  updateLCD();
  recordingFile.flush();
  recordingFile.close();
  Serial.print("STOPPED ");
  Serial.print(currentFilename);
  Serial.print(" ROWS=");
  Serial.println(rowsWritten);
}

void startRecording() {
  if (recording) {
    Serial.println("ALREADY_RECORDING");
    return;
  }
  if (!storageOK || !sensorOK) {
    Serial.println("ERROR Storage or sensor not ready");
    return;
  }
  String path = nextSessionPath();
  if (path.isEmpty()) {
    Serial.println("ERROR No free session filenames");
    return;
  }
  if (LittleFS.totalBytes() - LittleFS.usedBytes() < MIN_FREE_BYTES) {
    Serial.println("ERROR Storage nearly full");
    return;
  }
  recordingFile = LittleFS.open(path, "w");
  if (!recordingFile) {
    Serial.println("ERROR Could not create session");
    return;
  }
  if (recordingFile.println("elapsed_seconds,co2_ppm,temp_c,humidity_pct") == 0) {
    recordingFile.close();
    LittleFS.remove(path);
    Serial.println("ERROR Could not write CSV header");
    return;
  }
  recordingFile.flush();
  currentFilename = path;
  rowsWritten = 0;
  sessionStartMs = millis();
  lastCheckMs = sessionStartMs - RECORD_INTERVAL_MS;
  recording = true;
  updateLCD();
  Serial.print("RECORDING ");
  Serial.println(currentFilename);
}

void takeReading() {
  bool ready = false;
  int16_t error = sensor.getDataReadyStatus(ready);
  if (error != 0) {
    Serial.print("ERROR Sensor ready check: ");
    Serial.println(error);
    return;
  }
  if (!ready) return;

  uint16_t co2 = 0;
  float temperature = 0;
  float humidity = 0;
  error = sensor.readMeasurement(co2, temperature, humidity);
  if (error != 0 || co2 == 0) {
    Serial.print("ERROR Sensor measurement: ");
    Serial.println(error);
    return;
  }

  lastCo2 = co2;
  lastTemperature = temperature;
  lastHumidity = humidity;
  hasReading = true;
  updateLCD();

  if (!recording) return;

  uint32_t elapsed = (millis() - sessionStartMs) / 1000;
  String row = String(elapsed) + "," + String(co2) + "," +
               String(temperature, 2) + "," + String(humidity, 2);
  if (recordingFile.println(row) == 0) {
    Serial.println("ERROR Write failed");
    stopRecording();
    return;
  }
  recordingFile.flush();
  rowsWritten++;
  Serial.println(row);
  if (LittleFS.totalBytes() - LittleFS.usedBytes() < MIN_FREE_BYTES) {
    Serial.println("ERROR Storage nearly full; stopping");
    stopRecording();
  }
}

void listFiles() {
  if (!storageOK) {
    Serial.println("ERROR Storage not initialized");
    return;
  }
  Serial.println("LIST_BEGIN");
  File root = LittleFS.open("/");
  File file = root.openNextFile();
  while (file) {
    if (!file.isDirectory()) {
      String name = String(file.name());
      if (name.startsWith("/")) name.remove(0, 1);
      if (!sessionPath(name).isEmpty()) {
        Serial.print("FILE:");
        Serial.print(name);
        Serial.print(":");
        Serial.println(file.size());
      }
    }
    file.close();
    file = root.openNextFile();
  }
  root.close();
  Serial.println("LIST_END");
}

void download(const String& name) {
  if (recording) {
    Serial.println("ERROR Send STOP before downloading");
    return;
  }
  String path = sessionPath(name);
  if (path.isEmpty() || !LittleFS.exists(path)) {
    Serial.println("ERROR File not found");
    return;
  }
  File file = LittleFS.open(path, "r");
  if (!file) {
    Serial.println("ERROR Could not open file");
    return;
  }
  Serial.print("CSV_BEGIN:");
  Serial.println(name);
  while (file.available()) {
    Serial.write(file.read());
  }
  file.close();
  Serial.print("CSV_END:");
  Serial.println(name);
}

void deleteFile(const String& name) {
  if (recording) {
    Serial.println("ERROR Send STOP before deleting");
    return;
  }
  String path = sessionPath(name);
  if (path.isEmpty() || !LittleFS.exists(path)) {
    Serial.println("ERROR File not found");
    return;
  }
  Serial.println(LittleFS.remove(path) ? "DELETED" : "ERROR Delete failed");
}

void showStatus() {
  Serial.printf("STATUS storage=%s sensor=%s recording=%s rows=%lu used=%lu total=%lu\n",
                storageOK ? "OK" : "ERROR",
                sensorOK ? "OK" : "ERROR",
                recording ? "YES" : "NO",
                (unsigned long)rowsWritten,
                (unsigned long)(storageOK ? LittleFS.usedBytes() : 0),
                (unsigned long)(storageOK ? LittleFS.totalBytes() : 0));
}

void handleCommand(String command) {
  command.trim();
  String upper = command;
  upper.toUpperCase();
  if (upper == "STOP") stopRecording();
  else if (upper == "START") startRecording();
  else if (upper == "LIST") listFiles();
  else if (upper == "STATUS") showStatus();
  else if (upper.startsWith("DOWNLOAD ")) download(command.substring(9));
  else if (upper.startsWith("DELETE ")) deleteFile(command.substring(7));
  else if (upper == "HELP") Serial.println("COMMANDS STATUS LIST STOP START DOWNLOAD filename DELETE filename HELP");
  else Serial.println("ERROR Unknown command");
}

void setup() {
  Serial.begin(115200);
  lcd.begin(16, 2);
  lcdLine(0, "Offline CO2 Logger");
  lcdLine(1, "Starting...");
  delay(500);
  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(100000);

  // Never automatically format existing files.
  storageOK = LittleFS.begin(false);
  Serial.println(storageOK ? "LittleFS OK" : "ERROR LittleFS mount failed");

  sensor.begin(Wire, SCD41_I2C_ADDR_62);
  delay(30);
  sensor.stopPeriodicMeasurement();
  delay(500);
  int16_t error = sensor.startPeriodicMeasurement();
  sensorOK = (error == 0);
  if (!sensorOK) {
    Serial.print("ERROR SCD41 start: ");
    Serial.println(error);
  }

  if (sensorOK && storageOK) startRecording();
  else Serial.println("ERROR Cannot auto-record; check storage/sensor");
  updateLCD();
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\r' || c == '\n') {
      if (commandBuffer.length()) {
        handleCommand(commandBuffer);
        commandBuffer = "";
      }
    } else if (commandBuffer.length() < 100) {
      commandBuffer += c;
    }
  }
  if (sensorOK && millis() - lastCheckMs >= RECORD_INTERVAL_MS) {
    lastCheckMs = millis();
    takeReading();
  }
  delay(10);
}
