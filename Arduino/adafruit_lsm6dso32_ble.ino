/* ============================================================================
 *  Project: BLE IMU Orientation Streaming (UNO R4)
 *  Description: 
 *    Reads acceleration and gyroscope data from the LSM6DSO32 IMU,
 *    applies Madgwick sensor fusion to compute roll, pitch, and yaw,
 *    and transmits orientation data over BLE using Nordic UART service.
 *
 *  Hardware:
 *    - Arduino UNO R4 WiFi
 *    - Adafruit LSM6DSO32 IMU
 *    - BLE Central device (e.g., phone or PC)
 *
 *  Author: Josiah Bizure
 *  Date: 05/30/2025
 * ========================================================================== */

 /* ============================================================================
    TODO:
 *  - add timestamps for when we read the raw IMU values (Possibly when we send the data, think about which later)
 *  - Handling BLE disconnects more gracefully
 *  - Supporting configureable output formats (CSV, JSON, etc.)
 *  - Changed BLE buffer from 512 to 182; adjust if MTU negotiation fails
 *  - Using 128-byte buffer for orientation string; monitor usage and resize if needed
 * ========================================================================== */

// ============================================================================
//                              Includes
// ============================================================================

#include <Wire.h>              // Arduino I2C communication
#include <Adafruit_Sensor.h>   // Common interface for LSM6DSOX sensor family
#include <Adafruit_LSM6DSOX.h> // LSM6DSO32 IMU driver
#include <MadgwickAHRS.h>      // Sensor fusion filter
#include <ArduinoBLE.h>        // BLE support for UNO R4 Wifi

// ============================================================================
//                            Constants & Globals
// ============================================================================

constexpr float SAMPLE_RATE_HZ = 100.0f;  // Match with loop delay
constexpr int LOOP_DELAY_MS = 100;        // Delay per loop in milliseconds

Adafruit_LSM6DSOX imu;
Madgwick filter;

// Nordic UART Service UUIDs: used for custom BLE serial communication
const char* serviceUUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E";
const char* rxUUID      = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"; // Client to Arduino
const char* txUUID      = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"; // Arduino to Client

BLEService uartService(serviceUUID);
BLECharacteristic txChar(txUUID, BLENotify, 512);
BLECharacteristic rxChar(rxUUID, BLEWrite, 512);

// ============================================================================
//                         System Initialization
// ============================================================================

void InitializeIMUAndBLE() {
  Serial.begin(115200); // USB <--> PC

  // Initialize IMU over I2C on Wire1
  if (!imu.begin_I2C(LSM6DS_I2CADDR_DEFAULT, &Wire1)) {
    Serial.println("Failed to find LSM6DS032 chip");
    while (true) delay(10); // Halt if IMU not found
  }
  Serial.println("LSM6DS032 Found!");

  // Start Madgwick sensor fusion filter
  filter.begin(SAMPLE_RATE_HZ);

  // Initialize BLE peripheral
  if (!BLE.begin()) {
    Serial.println("Failed to start BLE");
    while (true); // Halt if BLE fails to initialize
  }

  BLE.setLocalName("UNO_R4_UART");       // What shows up to clients scanning for devices
  BLE.setDeviceName("UNO_R4_UART");      // Internal BLE identifier
  BLE.setAvertisedService(uartService);

  uartService.addCharacteristic(txChar); // Outgoing data to client
  uartService.addCharacteristic(rxChar); // Incoming data from client
  BLE.addService(uartService);           // Register service with BLE stack

  BLE.advertise();                       // Start BLE advertising to be discoverable
  Serial.println("BLE device active, waiting for connections...");
}

// ============================================================================
//                          Sensor Data Acquisition
// ============================================================================

void ReadSensorData(sensors_event_t &accel, sensors_event_t &gyro) {
  imu.getEvent(&accel, &gyro, nullptr); // Populate event structs with raw data
}

// ============================================================================
//                          Serial Output for Debugging
// ============================================================================

// Pre sensor fusion
void DisplaySensorData(const sensors_event_t &accel, const sensors_event_t &gyro) {
  // Acceleration [m/s^2]
  Serial.print("Accel X: "); Serial.print(accel.acceleration.x);
  Serial.print(" Y: "); Serial.print(accel.acceleration.y);
  Serial.print(" Z: "); Serial.println(accel.acceleration.z);

  // Angular Velocity [rad/s]
  Serial.print("Gyro X: "); Serial.print(gyro.gyro.x);
  Serial.print(" Y: "); Serial.print(gyro.gyro.y);
  Serial.print(" Z: "); Serial.println(gyro.gyro.z);
}

// Post sensor fusion
void DisplayOrientation(float roll, float pitch, float yaw) {
  Serial.print("Fusion orientation ");
  Serial.print("roll: "); Serial.println(roll);
  Serial.print("pitch: "); Serial.println(pitch);
  Serial.print("yaw: "); Serial.println(yaw);
}

// ============================================================================
//                       Orientation Computation (Madgwick)
// ============================================================================

void ComputeOrientation(const sensors_event_t &accel, const sensors_event_t &gyro,
                        float &roll, float &pitch, float &yaw) {
  // Convert gyroscope data from rad/s to deg/s
  const float gx = gyro.gyro.x * 180.0f / PI;
  const float gy = gyro.gyro.y * 180.0f / PI;
  const float gz = gyro.gyro.z * 180.0f / PI;

  // Feed Raw Sensor Data to the Filter
  filter.updateIMU(gx, gy, gz,
                   accel.acceleration.x,
                   accel.acceleration.y,
                   accel.acceleration.z);

  // Get Orientation in degrees (Euler Angles)
  roll  = filter.getRoll();
  pitch = filter.getPitch();
  yaw   = filter.getYaw();
}

// ============================================================================
//                    BLE orientation transmission (JSON)
// ============================================================================

void SendOrientation(float roll, float pitch, float yaw) {
  char buffer[128];  // Static buffer, BLE char limit is set to 128 bytes
  snprintf(buffer, sizeof(buffer),
           "{\"roll\":%.2f,\"pitch\":%.2f,\"yaw\":%.2f}",
           roll, pitch, yaw);
  txChar.writeValue(buffer);
}

// ============================================================================
//                            Arduino Entry Points
// ============================================================================

void setup() {
  InitializeIMUAndBLE();
}

void loop() {
  // Wait for a BLE central device to connect
  BLEDevice central = BLE.central();
  if (!central) return;

  Serial.print("Connected to "); Serial.println(central.address());

  sensors_event_t accel, gyro; // Sensor data structs
  float roll, pitch, yaw;      // Orientation output in degrees

  // Stay in this loop as long as the central device is connected
  while (central.connected()) {
    // Read raw sensor data
    ReadSensorData(accel, gyro);

    // Print raw data to Serial Monitor for debugging
    DisplaySensorData(accel, gyro);

    // Compute orientation from sensor data using Madgwick filter
    ComputeOrientation(accel, gyro, roll, pitch, yaw);

    // Print orientation to Serial Monitor for debugging
    DisplayOrientation(roll, pitch, yaw);

    // Transmit orientation data via BLE
    SendOrientation(roll, pitch, yaw);

    // Wait before next sample (controls sample rate)
    delay(LOOP_DELAY_MS);
  }
}