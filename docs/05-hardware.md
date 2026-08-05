# Hardware

The collar reuses the ESP32 + MPU6050 stack from the team's previous
crash-detection project. Nothing here has been built or measured — see
[§7](#7-what-is-estimated-and-what-is-measured).

---

## 1. Bill of materials

| # | Component | Purpose | Approx. ₹ |
|---|---|---|---|
| 1 | ESP32-WROOM-32 DevKit v1 | MCU, BLE, dual core | 350 |
| 2 | MPU6050 6-axis IMU | 3-axis accel + 3-axis gyro | 120 |
| 3 | MicroSD card module (SPI) | Local alert log when the phone is unreachable | 90 |
| 4 | 3.7 V Li-Po, 1200 mAh + TP4056 | Power and charging | 450 |
| 5 | LEDs (red, green) + 220 Ω | Status and alert indication | 20 |
| 6 | Active buzzer | Local audible alert | 30 |
| 7 | Collar strap, enclosure, wiring | Mechanical | 300 |
| | **Total** | | **≈ ₹1360** |

Deliberately absent, unlike the previous project:

- **No GPS on the collar.** The phone already has one, is better at it, and is
  where the escalation message is composed. A second GPS would cost ~37 mA
  continuously — more than everything else combined.
- **No GSM module.** The relay handles cellular. A SIM900A draws 2 A peaks and
  needs its own supply; nothing a dog should wear.
- **No vibration sensor.** The IMU covers the same signal with more information.

---

## 2. Pin map

| ESP32 pin | Connects to | Bus |
|---|---|---|
| GPIO 21 | MPU6050 SDA | I²C, 400 kHz |
| GPIO 22 | MPU6050 SCL | I²C |
| GPIO 5 | SD card CS | SPI |
| GPIO 23 | SD card MOSI | SPI |
| GPIO 19 | SD card MISO | SPI |
| GPIO 18 | SD card SCK | SPI |
| GPIO 27 | Green LED (armed) → 220 Ω → GND | GPIO |
| GPIO 26 | Red LED (alert) → 220 Ω → GND | GPIO |
| GPIO 14 | Active buzzer | GPIO |
| GPIO 34 | Battery sense, 2:1 divider | ADC1, input-only |
| 3V3 / GND | MPU6050, SD module, indicators | Power |

GPIO 34 is input-only, which is what it is for. The ADC2 pins are unusable while
Wi-Fi or BLE is active — a classic ESP32 trap and the reason battery sense is on
ADC1.

```
            ┌──────────────────┐
  MPU6050   │                  │   3.3 V ──┬── MPU6050 VCC
  SDA ──────┤ 21          5 ├──── SD CS    ├── SD VCC
  SCL ──────┤ 22         23 ├──── SD MOSI  └── (LEDs via 220 Ω)
            │            19 ├──── SD MISO
  Green ────┤ 27         18 ├──── SD SCK
  Red   ────┤ 26            │
  Buzzer ───┤ 14         34 ├──── batt sense ── 100k ─┬─ V+
            │      ESP32    │                    100k ┴─ GND
            └──────────────────┘
```

4.7 kΩ pull-ups on SDA and SCL. Most MPU6050 breakout boards include them; if two
I²C devices are ever added, remove the duplicates.

---

## 3. MPU6050 configuration

Set by `mpu_begin()` in `collar.ino`:

| Register | Value | Why |
|---|---|---|
| `PWR_MGMT_1` | `0x01` | Clock from the X gyro — more stable than the internal oscillator |
| `CONFIG` (DLPF) | `0x04` (21 Hz) | Sampling at 51.2 Hz puts Nyquist at 25.6 Hz. Anything above that **aliases into the band the spectral features read.** The spin's energy is below 10 Hz; what this removes is collar rattle and paw-impact ringing |
| `ACCEL_CONFIG` | `0x10` (±8 g) | Covers impulsive paw strikes during a rapid turn |
| `GYRO_CONFIG` | `0x18` (±2000 °/s) | A trained spin peaks around 500–600 °/s; ±2000 leaves headroom without wasting resolution |

### 3.1 Unit conversion — the most dangerous constant in the firmware

The model was trained on Shimmer3 data in **m/s²** and **deg/s**. Its thresholds
are in those units.

```c
accel_m_s2 = (raw / 4096.0f) * 9.80665f;   /* ±8 g      → LSB/g   = 4096  */
gyro_dps   =  raw / 16.4f;                 /* ±2000 °/s → LSB/dps = 16.4  */
```

A wrong constant here crashes nothing. It quietly moves every feature off the
model's operating point, and the collar keeps running, keeps reporting
confidences, and detects nothing. This is the hardest class of bug to notice in
the field, which is why the conversion is documented at the constant itself and
again here.

---

## 4. Power budget

| Component | Current | Duty |
|---|---|---|
| ESP32, BLE advertising, no connection | ~40 mA | continuous |
| ESP32, active BLE connection | ~80 mA | continuous |
| MPU6050 | 3.9 mA | continuous |
| SD card | 0.5 mA idle, ~100 mA write | writes only on alert |
| LEDs + buzzer | ~5 mA green, ~20 mA on alert | mostly green |
| **Steady state** | **≈ 50 mA** | |

At 1200 mAh: **≈ 24 h**. Enough for a day's wear with an overnight charge, which
is the realistic usage pattern.

The dominant cost is the ESP32 radio, not the sensing. Light-sleep between
strides — the CPU is idle for most of each 1.3 s — is the obvious next
optimisation and is not implemented.

---

## 5. Firmware footprint

| Item | Size |
|---|---|
| Forest tables (32 trees, 2862 nodes) | 39.2 KiB flash |
| `ca_scratch` working buffers | ~12 KiB RAM |
| Ring buffer (200 × 6 × 4 B) | 4.8 KiB RAM |
| Feature vector (159 × 4 B) | 0.6 KiB RAM |

`ca_scratch` is a file-scope static, not a stack local: 12 KiB would overflow a
default FreeRTOS task stack.

---

## 6. Core assignment

| Core | Task | Priority |
|---|---|---|
| 0 | IMU sampling, driven by a hardware timer | `configMAX_PRIORITIES - 1` |
| 1 | Feature extraction, inference, BLE, SD | default (`loop()`) |

The frequency features assume a uniform 51.2 Hz interval, so sampling jitter
distorts them directly. Core 0 does nothing else. The eight 133-point DFTs — the
most expensive thing the collar does — stay on core 1 where being late costs
latency rather than correctness.

---

## 7. What is estimated and what is measured

**No hardware was built.** Every current, runtime and cost figure above is a
datasheet estimate.

What *is* verified: the algorithmic core compiles as portable C and passes 240
checks against golden vectors from the real dataset, with zero vote-decision
disagreements against scikit-learn
([07-evaluation.md §7](07-evaluation.md#7-on-device-parity)).

What is not:

| Unverified | Risk |
|---|---|
| Execution timing on real silicon | DFT cost estimated at a few ms, unmeasured |
| **MPU6050 vs Shimmer3 response** | **Highest risk.** Different noise floor, DLPF characteristic and mounting. May require retraining on MPU6050 data |
| BLE range and reconnection with a dog outdoors | Unknown |
| Battery life | Calculated, not run down |
| Sampling jitter under load | Assumed uniform |
| Enclosure, ingress protection, comfort, welfare in wear | Not addressed |

The first hardware step should be recording a dog performing cued spins with a
Shimmer3 and an MPU6050 collar **simultaneously**, and comparing the feature
distributions. If they differ materially, the model must be retrained.

---

## 8. Assembly notes

1. Flash before assembly — the USB port is awkward once the collar is closed.
2. Mount the IMU **rigidly** to the strap. A sensor that can shift relative to the
   collar adds motion the model has never seen.
3. Orientation is not critical: the selected feature set includes three
   rotation-invariant magnitude features precisely because a collar rotates.
4. The buzzer is a genuine escalation path in its own right — if a person is
   nearby, the fastest route to help involves no phone at all.
5. Keep the battery and charging circuit away from the dog's skin, and fuse the
   Li-Po. This is an animal welfare requirement, not an electrical preference.
