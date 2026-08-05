/* Feature extraction -- see ca_features.h.
 *
 * Every routine here mirrors a specific NumPy call, including its conventions:
 * population standard deviation (ddof=0), linear-interpolated percentiles,
 * first-index argmax on ties, and signbit-based mean crossings.  Where NumPy's
 * convention is not the obvious one, the comment says which call is being
 * matched, because that is the thing a future edit is most likely to break.
 */

#include "ca_features.h"

#include <math.h>
#include <stddef.h>
#include <string.h>

#define CA_EPS 1e-12f

/* ---------------------------------------------------------------------- */
/* helpers                                                                */
/* ---------------------------------------------------------------------- */

static void ca_sort_ascending(ca_real *values, size_t n)
{
    /* Insertion sort: n is 133 and this runs once per signal per window, so an
     * O(n^2) sort costs ~9k comparisons at 0.77 Hz.  Not worth a heap sort's
     * extra code for the flash it would take. */
    for (size_t i = 1; i < n; ++i) {
        ca_real key = values[i];
        size_t j = i;
        while (j > 0 && values[j - 1] > key) {
            values[j] = values[j - 1];
            --j;
        }
        values[j] = key;
    }
}

/* numpy.percentile with the default 'linear' interpolation, on sorted input. */
static ca_real ca_percentile_sorted(const ca_real *sorted, size_t n, ca_real q)
{
    if (n == 0) {
        return 0.0f;
    }
    if (n == 1) {
        return sorted[0];
    }
    ca_real position = (q / 100.0f) * (ca_real)(n - 1);
    size_t lower = (size_t)floorf(position);
    size_t upper = lower + 1u;
    if (upper >= n) {
        return sorted[n - 1];
    }
    ca_real fraction = position - (ca_real)lower;
    return sorted[lower] + fraction * (sorted[upper] - sorted[lower]);
}

/* numpy.median: for odd n the middle element, for even n the mean of the two
 * straddling it. */
static ca_real ca_median_sorted(const ca_real *sorted, size_t n)
{
    if (n == 0) {
        return 0.0f;
    }
    if (n % 2u == 1u) {
        return sorted[n / 2u];
    }
    return 0.5f * (sorted[n / 2u - 1u] + sorted[n / 2u]);
}

/* ---------------------------------------------------------------------- */
/* derived signals                                                        */
/* ---------------------------------------------------------------------- */

static void ca_derive_signals(const ca_real *window, size_t n_samples,
                              ca_scratch *scratch)
{
    for (size_t i = 0; i < n_samples; ++i) {
        const ca_real *row = &window[i * CA_N_CHANNELS];
        for (size_t c = 0; c < CA_N_CHANNELS; ++c) {
            scratch->signals[c][i] = row[c];
        }
        /* Magnitudes are rotation-invariant, which matters because a collar
         * rotates freely around the dog's neck between fittings. */
        scratch->signals[6][i] =
            sqrtf(row[0] * row[0] + row[1] * row[1] + row[2] * row[2]);
        scratch->signals[7][i] =
            sqrtf(row[3] * row[3] + row[4] * row[4] + row[5] * row[5]);
    }
}

/* ---------------------------------------------------------------------- */
/* time domain                                                            */
/* ---------------------------------------------------------------------- */

static void ca_time_features(const ca_real *x, size_t n, ca_scratch *scratch,
                             ca_real *out)
{
    ca_real sum = 0.0f;
    ca_real sum_squares = 0.0f;
    ca_real minimum = x[0];
    ca_real maximum = x[0];

    for (size_t i = 0; i < n; ++i) {
        sum += x[i];
        sum_squares += x[i] * x[i];
        if (x[i] < minimum) {
            minimum = x[i];
        }
        if (x[i] > maximum) {
            maximum = x[i];
        }
    }

    ca_real mean = sum / (ca_real)n;
    ca_real energy = sum_squares / (ca_real)n;

    /* Two-pass moments.  The textbook one-pass form (E[x^2] - mean^2) is a
     * difference of two large, nearly equal float32 quantities: on a gyro
     * channel sitting at a few hundred deg/s it loses most of its significant
     * digits, and the error is then cubed and raised to the fourth power by
     * skew and kurtosis.  Measured against NumPy on real windows, one-pass gave
     * relative errors up to 5.6e-2 on kurtosis; two-pass brings them under
     * 1e-3.  NumPy is two-pass for the same reason. */
    ca_real second = 0.0f;
    ca_real abs_deviation = 0.0f;
    ca_real third = 0.0f;
    ca_real fourth = 0.0f;
    size_t crossings = 0u;
    int previous_negative = 0;

    for (size_t i = 0; i < n; ++i) {
        ca_real d = x[i] - mean;
        ca_real d2 = d * d;
        second += d2;
        abs_deviation += fabsf(d);
        third += d2 * d;
        fourth += d2 * d2;

        /* numpy.signbit: -0.0 counts as negative.  Using (d < 0) instead would
         * disagree on an exactly-constant signal. */
        int negative = signbit(d) ? 1 : 0;
        if (i > 0u && negative != previous_negative) {
            ++crossings;
        }
        previous_negative = negative;
    }

    ca_real std = sqrtf(second / (ca_real)n);

    ca_real skew = 0.0f;
    ca_real kurtosis = 0.0f;
    if (std >= CA_EPS) {
        ca_real std3 = std * std * std;
        skew = (third / (ca_real)n) / std3;
        kurtosis = (fourth / (ca_real)n) / (std3 * std) - 3.0f;
    }

    memcpy(scratch->sorted, x, n * sizeof(ca_real));
    ca_sort_ascending(scratch->sorted, n);
    ca_real q25 = ca_percentile_sorted(scratch->sorted, n, 25.0f);
    ca_real q75 = ca_percentile_sorted(scratch->sorted, n, 75.0f);

    out[CA_T_MEAN] = mean;
    out[CA_T_STD] = std;
    out[CA_T_MIN] = minimum;
    out[CA_T_MAX] = maximum;
    out[CA_T_RANGE] = maximum - minimum;
    out[CA_T_MEDIAN] = ca_median_sorted(scratch->sorted, n);
    out[CA_T_IQR] = q75 - q25;
    out[CA_T_RMS] = sqrtf(energy);
    out[CA_T_MAD] = abs_deviation / (ca_real)n;
    out[CA_T_SKEW] = skew;
    out[CA_T_KURTOSIS] = kurtosis;
    out[CA_T_MCR] = (n > 1u) ? (ca_real)crossings / (ca_real)(n - 1u) : 0.0f;
    out[CA_T_ENERGY] = energy;
}

/* ---------------------------------------------------------------------- */
/* frequency domain                                                       */
/* ---------------------------------------------------------------------- */

static void ca_freq_features(const ca_real *x, size_t n, ca_real fs_hz,
                             ca_scratch *scratch, ca_real *out)
{
    /* A direct DFT rather than an FFT.  The window is 133 samples, which is not
     * a power of two, so a radix-2 FFT would need zero-padding to 256 -- and
     * that changes the spectrum, so the device would no longer compute the same
     * features the model was trained on.  At 133 points the O(n^2) transform is
     * ~18k complex multiply-accumulates per signal; eight signals every 1.3 s
     * is a few milliseconds on a 240 MHz core, which the collar can afford. */
    ca_real mean = 0.0f;
    for (size_t i = 0; i < n; ++i) {
        mean += x[i];
    }
    mean /= (ca_real)n;
    for (size_t i = 0; i < n; ++i) {
        scratch->centred[i] = x[i] - mean;
    }

    /* numpy.fft.rfft yields n/2 + 1 bins; bin 0 is DC and is dropped, since
     * centring already zeroed it and it would otherwise dominate the
     * normalised distribution used for entropy and centroid. */
    size_t n_bins = n / 2u + 1u;
    const ca_real two_pi_over_n = (ca_real)(2.0 * M_PI) / (ca_real)n;

    ca_real total = 0.0f;
    size_t dominant = 1u;
    ca_real peak = -1.0f;

    for (size_t k = 1u; k < n_bins; ++k) {
        ca_real real_part = 0.0f;
        ca_real imag_part = 0.0f;
        ca_real angle_step = two_pi_over_n * (ca_real)k;
        for (size_t i = 0; i < n; ++i) {
            ca_real angle = angle_step * (ca_real)i;
            real_part += scratch->centred[i] * cosf(angle);
            imag_part -= scratch->centred[i] * sinf(angle);
        }
        ca_real magnitude_squared = real_part * real_part + imag_part * imag_part;
        ca_real power = magnitude_squared / (ca_real)n;
        scratch->power[k] = power;
        total += power;
        /* Strict '>' reproduces numpy.argmax's first-index-wins tie-break. */
        if (power > peak) {
            peak = power;
            dominant = k;
        }
    }

    ca_real bin_hz = fs_hz / (ca_real)n;
    ca_real denominator = (total > CA_EPS) ? total : CA_EPS;
    ca_real entropy = 0.0f;
    ca_real centroid = 0.0f;
    for (size_t k = 1u; k < n_bins; ++k) {
        ca_real p = scratch->power[k] / denominator;
        entropy -= p * logf(p + CA_EPS);
        centroid += p * ((ca_real)k * bin_hz);
    }

    out[CA_F_DOM_FREQ] = (ca_real)dominant * bin_hz;
    out[CA_F_SPEC_ENERGY] = total;
    out[CA_F_SPEC_ENTROPY] = entropy;
    out[CA_F_SPEC_CENTROID] = centroid;
    out[CA_F_PEAK_POWER] = (peak > 0.0f) ? peak : 0.0f;
}

/* ---------------------------------------------------------------------- */
/* correlations                                                           */
/* ---------------------------------------------------------------------- */

static void ca_correlations(const ca_scratch *scratch, size_t n, ca_real *out)
{
    ca_real means[CA_N_CHANNELS];
    ca_real stds[CA_N_CHANNELS];

    for (size_t c = 0; c < CA_N_CHANNELS; ++c) {
        ca_real sum = 0.0f;
        for (size_t i = 0; i < n; ++i) {
            sum += scratch->signals[c][i];
        }
        means[c] = sum / (ca_real)n;

        ca_real variance = 0.0f;
        for (size_t i = 0; i < n; ++i) {
            ca_real d = scratch->signals[c][i] - means[c];
            variance += d * d;
        }
        stds[c] = sqrtf(variance / (ca_real)n);
    }

    /* Pair order must match features.py::_pairs(): i ascending, then j > i. */
    size_t index = 0u;
    for (size_t i = 0; i < CA_N_CHANNELS; ++i) {
        for (size_t j = i + 1u; j < CA_N_CHANNELS; ++j) {
            ca_real denominator = stds[i] * stds[j];
            if (denominator < CA_EPS) {
                out[index++] = 0.0f;
                continue;
            }
            ca_real covariance = 0.0f;
            for (size_t s = 0; s < n; ++s) {
                covariance += (scratch->signals[i][s] - means[i]) *
                              (scratch->signals[j][s] - means[j]);
            }
            covariance /= (ca_real)n;
            out[index++] = covariance / denominator;
        }
    }
}

/* ---------------------------------------------------------------------- */
/* entry points                                                           */
/* ---------------------------------------------------------------------- */

int ca_extract(const ca_real *window, size_t n_samples, ca_real fs_hz,
               ca_scratch *scratch, ca_real *out)
{
    if (n_samples == 0u || n_samples > CA_MAX_WINDOW) {
        return -1;
    }

    ca_derive_signals(window, n_samples, scratch);

    for (size_t s = 0; s < CA_N_SIGNALS; ++s) {
        ca_time_features(scratch->signals[s], n_samples, scratch,
                         &out[CA_TIME_OFFSET + s * CA_N_TIME_FEATURES]);
    }
    for (size_t s = 0; s < CA_N_SIGNALS; ++s) {
        ca_freq_features(scratch->signals[s], n_samples, fs_hz, scratch,
                         &out[CA_FREQ_OFFSET + s * CA_N_FREQ_FEATURES]);
    }
    ca_correlations(scratch, n_samples, &out[CA_CORR_OFFSET]);

    /* A NaN reaching the forest would compare false against every threshold and
     * walk a deterministic but meaningless path.  Clamp instead. */
    for (size_t f = 0; f < CA_FEATURE_COUNT; ++f) {
        if (!isfinite(out[f])) {
            out[f] = 0.0f;
        }
    }
    return 0;
}

ca_real ca_gyro_magnitude_mean(const ca_real *window, size_t n_samples)
{
    if (n_samples == 0u) {
        return 0.0f;
    }
    ca_real total = 0.0f;
    for (size_t i = 0; i < n_samples; ++i) {
        const ca_real *row = &window[i * CA_N_CHANNELS];
        total += sqrtf(row[3] * row[3] + row[4] * row[4] + row[5] * row[5]);
    }
    return total / (ca_real)n_samples;
}
