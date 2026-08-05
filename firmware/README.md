# Collar firmware

ESP32 + MPU6050. Detects the dog's trained spin alert, verifies it across
several windows, and relays a confirmed alert to the owner's phone over BLE.

## Layout

| File | Arduino-free? | Purpose |
|---|---|---|
| `collar/collar.ino` | no | Hardware glue: sampling, BLE, LEDs, SD |
| `collar/src/ca_features.[ch]` | **yes** | 159-feature extraction, port of `features.py` |
| `collar/src/ca_forest.[ch]` | **yes** | Forest inference over the generated tables |
| `collar/src/ca_verify.[ch]` | **yes** | K-of-N verification gate + refractory period |
| `collar/src/ca_ring.[ch]` | **yes** | Tear-detecting sample ring |
| `collar/src/model.h` | **yes** | **Generated.** Do not edit by hand |
| `test/test_native.c` | — | Host test against golden vectors from the real dataset |

The algorithmic core has no Arduino, FreeRTOS or ESP-IDF dependency. That is
what makes it testable on a laptop — and the only reason we can claim the C
computes the same thing as the Python the model was trained on.

## Verify the port (no hardware needed)

```bash
python ml/scripts/make_firmware_vectors.py   # 64 real windows + expected outputs
make -C firmware/test run
```

```
collar core tests -- 64 golden windows from the real dataset

geometry
feature extraction vs ml/canine_alert/features.py
  worst relative error 2.99e-03
forest inference vs scikit-learn
  worst end-to-end probability difference 1.79e-07
verification gate vs ml/canine_alert/verification.py
sample ring
degenerate inputs

240 checks, 0 failures
PASS
```

Zero of the 64 windows vote differently on-device than in scikit-learn.

## Regenerate the model

```bash
python ml/scripts/run_experiments.py         # picks the operating point
python ml/scripts/export_firmware_model.py   # -> collar/src/model.h
python ml/scripts/make_firmware_vectors.py   # -> test/vectors.bin
make -C firmware/test run                    # confirm the new model still agrees
```

The exporter refuses to write the header if the transpiled forest disagrees with
scikit-learn by more than 1e-6, and it reads the verification policy back from
`results.json` — so the firmware always ships the configuration the evaluation
actually selected.

## Build for the board

Arduino IDE 2.3.x, esp32 board support 2.0.x, board "ESP32 Dev Module". Open
`collar/collar.ino` and upload. Libraries (Wire, SPI, SD, BLE) all ship with the
core.

Set `DOG_ID` at the top of the sketch before flashing.

## Not verified

**This has never run on an ESP32.** No board was available. Timing, MPU6050
response versus the Shimmer3 the model was trained on, BLE range and battery life
are all estimated. See [../docs/09-limitations.md](../docs/09-limitations.md) §3.
