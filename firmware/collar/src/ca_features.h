/* On-device feature extraction -- portable C, no Arduino dependency.
 *
 * This is a direct port of ml/canine_alert/features.py.  The two must agree:
 * the model's thresholds were learned on the Python features, so a divergence
 * here silently changes what the collar detects.  firmware/test/test_native.c
 * checks the port against golden vectors generated from the real dataset.
 *
 * Deliberately free of Arduino, FreeRTOS and ESP-IDF headers so it compiles and
 * runs on a host for testing.
 */

#ifndef CA_FEATURES_H
#define CA_FEATURES_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Single precision throughout: the ESP32's FPU is single-precision only, and
 * doubles are software-emulated at roughly 50x the cost. */
typedef float ca_real;

#define CA_N_CHANNELS 6 /* ax ay az gx gy gz, in this order */
#define CA_N_SIGNALS 8  /* the six channels plus |accel| and |gyro| */
#define CA_N_TIME_FEATURES 13
#define CA_N_FREQ_FEATURES 5
#define CA_N_CORR_FEATURES 15 /* pairs among the six raw channels */

#define CA_FEATURE_COUNT                                     \
    (CA_N_SIGNALS * CA_N_TIME_FEATURES +                     \
     CA_N_SIGNALS * CA_N_FREQ_FEATURES + CA_N_CORR_FEATURES)

/* Largest window the scratch buffers are sized for.  CA_WINDOW_SAMPLES from
 * model.h must not exceed this. */
#define CA_MAX_WINDOW 160

/* Offsets into the feature vector, matching the concatenation order in
 * features.py: [time | frequency | correlation]. */
#define CA_TIME_OFFSET 0
#define CA_FREQ_OFFSET (CA_N_SIGNALS * CA_N_TIME_FEATURES)
#define CA_CORR_OFFSET (CA_FREQ_OFFSET + CA_N_SIGNALS * CA_N_FREQ_FEATURES)

/* Index of each statistic within a signal's time-domain block. */
enum ca_time_feature {
    CA_T_MEAN = 0,
    CA_T_STD,
    CA_T_MIN,
    CA_T_MAX,
    CA_T_RANGE,
    CA_T_MEDIAN,
    CA_T_IQR,
    CA_T_RMS,
    CA_T_MAD,
    CA_T_SKEW,
    CA_T_KURTOSIS,
    CA_T_MCR,
    CA_T_ENERGY
};

/* Index of each statistic within a signal's frequency-domain block. */
enum ca_freq_feature {
    CA_F_DOM_FREQ = 0,
    CA_F_SPEC_ENERGY,
    CA_F_SPEC_ENTROPY,
    CA_F_SPEC_CENTROID,
    CA_F_PEAK_POWER
};

/* Scratch space for one window's worth of work.
 *
 * Allocated once by the caller (a static in the sampling task) rather than on
 * the stack: at CA_MAX_WINDOW = 160 this is about 12 kB, which would overflow
 * a default FreeRTOS task stack.
 */
typedef struct {
    ca_real signals[CA_N_SIGNALS][CA_MAX_WINDOW];
    ca_real centred[CA_MAX_WINDOW];
    ca_real sorted[CA_MAX_WINDOW];
    ca_real power[CA_MAX_WINDOW / 2 + 1];
} ca_scratch;

/* Build the full CA_FEATURE_COUNT feature vector from one window.
 *
 * `window` is row-major (n_samples x CA_N_CHANNELS), the same layout the IMU
 * ring buffer produces.  `out` must hold CA_FEATURE_COUNT reals.
 *
 * Returns 0 on success, -1 if n_samples exceeds CA_MAX_WINDOW.
 */
int ca_extract(const ca_real *window, size_t n_samples, ca_real fs_hz,
               ca_scratch *scratch, ca_real *out);

/* Mean gyroscope magnitude -- the heuristic baseline's statistic.  Kept so the
 * firmware can fall back to a threshold rule if the model is ever disabled. */
ca_real ca_gyro_magnitude_mean(const ca_real *window, size_t n_samples);

#ifdef __cplusplus
}
#endif

#endif /* CA_FEATURES_H */
