# Local hardware + dashboard integration (Windows)

This bundle adapts `firmware/collar/collar.ino` to the bench wiring currently used:

- MPU-compatible IMU: SDA GPIO 21, SCL GPIO 22, 3V3, GND
- Green LED: GPIO 4 through 220 Ω resistor to LED anode; cathode to GND
- Red LED: GPIO 18 through 220 Ω resistor to LED anode; cathode to GND
- Buzzer signal: GPIO 19 (keep the same safe supply/ground wiring that already worked)

**MicroSD is intentionally disabled in this bench version.** The planned SPI mapping uses GPIO 18/19, which conflicts with the current red LED and buzzer mapping. Do not enable SD until you reassign pins or move the SD SPI pins.

## What runs where

`ESP32 + IMU` (local model and verification gate) --BLE notifications--> `Python relay on this PC` (escalation state machine and console-only demo notifications) --HTTP--> `Python dev backend` (local alert history) --> `caregiver dashboard`.

The dashboard is an alert-history/audit dashboard, not a live XYZ plot. The project intentionally sends verified alert events, not continuous raw IMU samples. It refreshes about every 15 seconds.

## 1. Extract and check prerequisites

1. Extract this ZIP to a simple folder, for example `C:\Projects\dog-alert`.
2. Install Python 3.11 (64-bit) and ensure `py -3.11 --version` works.
3. In Arduino IDE 2.3.x, use **ESP32 by Espressif Systems 2.0.x** (the source uses the legacy ESP32 timer API; 2.0.17 is a suitable version). Select **ESP32 Dev Module**.
4. Bluetooth must be enabled on Windows. Keep the ESP32 within BLE range of this PC.

The backend and dashboard use only Python's standard library. BLE mode additionally needs `bleak`; full ML/data-analysis dependencies are only needed if retraining or running dataset replay scripts.

## 2. Create relay config (demo contact info only)

Open PowerShell in the project root:

```powershell
Copy-Item gateway\relay_config.example.json gateway\relay_config.json
```

The example contacts are placeholders. The current relay uses a **ConsoleNotifier**; it prints notification attempts in the terminal and does not send real SMS or push notifications. Keep placeholder contact values for bench testing. Firmware `DOG_ID` is `stuart`, matching the example config.

For a calm dashboard test, you can make the two timers long in `gateway\relay_config.json`:

```json
"timing": {
  "owner_ack_seconds": 3600,
  "caregiver_ack_seconds": 3600,
  "max_location_age_seconds": 300
}
```

Keep the JSON syntax valid (replace the existing `timing` object rather than adding a duplicate). This prevents the fake bench alert from advancing through the ladder while you inspect the dashboard. Restore shorter values only for a deliberate simulated escalation test.

## 3. Start the local backend/dashboard

Open **Terminal 1** (PowerShell), go to the extracted project root, and run:

```powershell
py -3.11 tools\devserver.py --port 8080
```

Keep this terminal running. Open these URLs:

- Dashboard: <http://127.0.0.1:8080/>
- Health check: <http://127.0.0.1:8080/health>
- Summary API: <http://127.0.0.1:8080/api/v1/summary>

The dev backend writes an append-only local log to `data\alerts.jsonl`. You do not need Maven, Open Liberty, React, npm, or a database for the local demo. The Java backend in `backend/` is a separate, not-yet-built alternative.

## 4. Install the BLE relay dependency

Open **Terminal 2** in the project root:

```powershell
py -3.11 -m pip install bleak
```

Start the relay, which scans for the BLE device name `AssistDogCollar-stuart`:

```powershell
py -3.11 gateway\relay.py --config gateway\relay_config.json --source ble --backend http://127.0.0.1:8080 --verbose
```

Wait until it says it found the collar and subscribed to notifications. Leave this terminal running. The relay's notification transport is console-only in this repository; it is not an installed Android/iOS app and it will not send real SMS/push messages.

## 5. Flash the adapted ESP32 collar firmware

1. In Arduino IDE choose **File → Open** and open `firmware\collar\collar.ino` from this extracted bundle. Keep its `src` folder alongside it.
2. Select **Tools → Board → ESP32 Arduino → ESP32 Dev Module** and the correct COM port.
3. Compile and upload.
4. Open Serial Monitor at **115200 baud**. The startup log should include the model/gate configuration, successful sensor startup, BLE advertising as `AssistDogCollar-stuart`, and `armed`.
5. Because this version is configured for the observed WHO_AM_I `0x70`, the firmware accepts that compatible device identity. The previous raw-read sketch is no longer needed after this firmware is flashed.

The adapted sketch uses your current pins and compiles in a bench-only `TEST_ALERT` command. SD-card initialisation is disabled for now so SPI does not reconfigure GPIO 18/19.

## 6. Verify the complete ESP32 → BLE → relay → dashboard route

1. Start the backend first (Terminal 1).
2. Start the BLE relay next (Terminal 2) and wait for it to connect.
3. Open Arduino Serial Monitor at 115200 baud, set line ending to **Newline** or **Both NL & CR**, and send this exact text:

```text
TEST_ALERT
```

4. Serial Monitor should print that a synthetic bench alert was injected and an `ALERT { ... }` JSON line. The relay terminal should show the event and a notification attempt; the Serial Monitor should then show a relay acknowledgement.
5. Open or refresh <http://127.0.0.1:8080/>. The new alert should appear after the dashboard's next poll (up to about 15 seconds). The alert should include the collar confidence and an audit trail.

`TEST_ALERT` intentionally **bypasses the classifier**. It tests only the BLE transport, relay, backend API, and dashboard. Do not interpret it as proof that real movement is classified correctly.

## 7. Test the real detector separately

After confirming the synthetic test route, leave the relay connected and gently move/rotate the sensor by hand. The firmware classifier looks for the trained spin-alert pattern across multiple windows; arbitrary shaking, tilting, or a single bump is not supposed to create an alert. Watch the Serial Monitor for:

```text
ALERT {"dog_id":"stuart", ...}
```

No alert from casual hand movement can be normal. If real detector performance needs evaluation, record representative movements and compare them with the training sensor/data. The model was trained from Shimmer3 recordings, not calibrated on your specific IMU module; the project README documents this as an unverified hardware risk.

## 8. Test the escalation ladder (optional)

The relay terminal prints each local notification attempt and the dashboard tracks transitions. This prototype does **not** include the phone UI needed for a real owner acknowledgement, real GPS acquisition, or a real SMS/push provider. For a controlled ladder demo only, use fake contact information and temporarily set short timers, e.g. owner 10 seconds and caregiver 15 seconds. After the demo, restore safe/long bench values.

## Troubleshooting

- **Relay says no collar found:** turn on Windows Bluetooth; ensure the new firmware is running and advertising; close any other app already connected to the ESP32; run relay with `--verbose` again.
- **No `armed` in Serial Monitor / red LED keeps blinking:** check I²C wiring and that the sensor still responds at `0x68` with identity `0x70`.
- **`TEST_ALERT` prints but nothing reaches dashboard:** verify Terminal 1 is running at port 8080, Terminal 2 includes `--backend http://127.0.0.1:8080`, and the relay printed `subscribed`.
- **Dashboard looks empty:** the dashboard shows alerts, not continuous IMU readings. Use `TEST_ALERT` while BLE is connected, then wait up to 15 seconds or refresh.
- **Compile errors for `timerBegin`, `timerAlarmWrite`, or `timerAlarmEnable`:** select an ESP32 board package from the 2.0.x line as specified above; package 3.x changed these timer APIs.
- **Board won't upload:** close Serial Monitor while uploading, reselect the correct COM port, and retry.

## Safety and deployment limitations

This is a research/bench prototype, not a certified medical or animal-safety product. Do not rely on it for seizure warning or emergency response, and do not attach it to a dog for real-world reliance. BLE range, the model's performance on this IMU, power/battery safety, contact delivery, phone background operation, authentication, and durable production storage need separate validation. Set `ENABLE_SERIAL_TEST_ALERTS` to `0` in `collar.ino` before any non-demo testing, and do not treat this Python PC relay as a mobile phone app.
