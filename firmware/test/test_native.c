/* Host test for the collar's algorithmic core.
 *
 * The ESP32 code that matters -- feature extraction, forest inference, the
 * verification gate -- is written as portable C with no Arduino dependency
 * precisely so it can be compiled and run here, against golden vectors taken
 * from the real dataset and the real trained model.
 *
 * Build and run:  make -C firmware/test run
 *
 * The two questions this answers:
 *   1. Does the C compute the same features as ml/canine_alert/features.py?
 *   2. Does the C forest reach the same decision as scikit-learn?
 *
 * Feature agreement is checked to a relative tolerance rather than exactly:
 * NumPy accumulates in float64 and the firmware in float32, because the ESP32's
 * FPU is single-precision.  The *decisions* are required to match exactly --
 * that is the property the evaluation numbers depend on.
 */

#include <math.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../collar/src/ca_features.h"
#include "../collar/src/ca_forest.h"
#include "../collar/src/ca_ring.h"
#include "../collar/src/ca_verify.h"
#include "../collar/src/model.h"

/* Relative tolerance for a single feature.  Chosen empirically as the level at
 * which float32 accumulation over 133 samples settles; anything looser would
 * stop catching real port bugs. */
#define FEATURE_REL_TOL 2e-3f
#define FEATURE_ABS_FLOOR 1e-4f

/* The forest is a step function of the features, so a feature that lands on the
 * wrong side of a split flips a whole subtree.  A small probability difference
 * is expected; a different decision is not. */
#define PROBA_ABS_TOL 0.02f

static int failures = 0;
static int checks = 0;

static void check(bool condition, const char *fmt, ...)
{
    ++checks;
    if (!condition) {
        ++failures;
        va_list args;
        va_start(args, fmt);
        fputs("  FAIL: ", stderr);
        vfprintf(stderr, fmt, args);
        fputc('\n', stderr);
        va_end(args);
    }
}

/* ---------------------------------------------------------------------- */
/* golden vectors                                                         */
/* ---------------------------------------------------------------------- */

typedef struct {
    uint32_t n_windows;
    uint32_t width;
    uint32_t n_channels;
    uint32_t n_features;
    uint32_t n_selected;
    float fs_hz;
    float *windows;  /* n_windows * width * n_channels */
    float *features; /* n_windows * n_features */
    float *scaled;   /* n_windows * n_selected */
    float *proba;    /* n_windows */
} vectors_t;

static bool load_vectors(const char *path, vectors_t *v)
{
    FILE *file = fopen(path, "rb");
    if (file == NULL) {
        fprintf(stderr, "cannot open %s\n", path);
        return false;
    }

    char magic[8];
    if (fread(magic, 1, 8, file) != 8 || memcmp(magic, "CAVEC001", 8) != 0) {
        fprintf(stderr, "%s is not a CAVEC001 vector file\n", path);
        fclose(file);
        return false;
    }

    if (fread(&v->n_windows, 4, 1, file) != 1 ||
        fread(&v->width, 4, 1, file) != 1 ||
        fread(&v->n_channels, 4, 1, file) != 1 ||
        fread(&v->n_features, 4, 1, file) != 1 ||
        fread(&v->n_selected, 4, 1, file) != 1 ||
        fread(&v->fs_hz, 4, 1, file) != 1) {
        fprintf(stderr, "truncated header in %s\n", path);
        fclose(file);
        return false;
    }

    size_t window_count = (size_t)v->n_windows * v->width * v->n_channels;
    size_t feature_count = (size_t)v->n_windows * v->n_features;
    size_t scaled_count = (size_t)v->n_windows * v->n_selected;

    v->windows = malloc(window_count * sizeof(float));
    v->features = malloc(feature_count * sizeof(float));
    v->scaled = malloc(scaled_count * sizeof(float));
    v->proba = malloc((size_t)v->n_windows * sizeof(float));
    if (!v->windows || !v->features || !v->scaled || !v->proba) {
        fprintf(stderr, "out of memory loading %s\n", path);
        fclose(file);
        return false;
    }

    bool ok = fread(v->windows, sizeof(float), window_count, file) == window_count &&
              fread(v->features, sizeof(float), feature_count, file) == feature_count &&
              fread(v->scaled, sizeof(float), scaled_count, file) == scaled_count &&
              fread(v->proba, sizeof(float), v->n_windows, file) == v->n_windows;
    fclose(file);
    if (!ok) {
        fprintf(stderr, "truncated payload in %s\n", path);
    }
    return ok;
}

static void free_vectors(vectors_t *v)
{
    free(v->windows);
    free(v->features);
    free(v->scaled);
    free(v->proba);
}

/* ---------------------------------------------------------------------- */
/* test: geometry agrees between the generator and the generated header   */
/* ---------------------------------------------------------------------- */

static void test_geometry(const vectors_t *v)
{
    printf("geometry\n");
    check(v->width == (uint32_t)CA_WINDOW_SAMPLES,
          "vector width %u != CA_WINDOW_SAMPLES %d", v->width, CA_WINDOW_SAMPLES);
    check(v->n_channels == (uint32_t)CA_N_CHANNELS,
          "vector channels %u != CA_N_CHANNELS %d", v->n_channels, CA_N_CHANNELS);
    check(v->n_features == (uint32_t)CA_FEATURE_COUNT,
          "vector features %u != CA_FEATURE_COUNT %d", v->n_features, CA_FEATURE_COUNT);
    check(v->n_features == (uint32_t)CA_N_ALL_FEATURES,
          "CA_FEATURE_COUNT %d != CA_N_ALL_FEATURES %d", CA_FEATURE_COUNT,
          CA_N_ALL_FEATURES);
    check(v->n_selected == (uint32_t)CA_N_FEATURES,
          "vector selected %u != CA_N_FEATURES %d", v->n_selected, CA_N_FEATURES);
    check(fabsf(v->fs_hz - CA_SAMPLE_RATE_HZ) < 0.01f,
          "vector fs %.4f != CA_SAMPLE_RATE_HZ %.4f", v->fs_hz, CA_SAMPLE_RATE_HZ);
    check(CA_WINDOW_SAMPLES <= CA_MAX_WINDOW,
          "CA_WINDOW_SAMPLES %d exceeds CA_MAX_WINDOW %d", CA_WINDOW_SAMPLES,
          CA_MAX_WINDOW);
}

/* ---------------------------------------------------------------------- */
/* test: features match Python                                            */
/* ---------------------------------------------------------------------- */

static void test_features(const vectors_t *v, ca_scratch *scratch)
{
    printf("feature extraction vs ml/canine_alert/features.py\n");

    static ca_real computed[CA_FEATURE_COUNT];
    float worst_relative = 0.0f;
    int worst_feature = -1;
    int worst_window = -1;
    int mismatches = 0;

    for (uint32_t w = 0; w < v->n_windows; ++w) {
        const float *window = &v->windows[(size_t)w * v->width * v->n_channels];
        const float *expected = &v->features[(size_t)w * v->n_features];

        int status = ca_extract(window, v->width, v->fs_hz, scratch, computed);
        check(status == 0, "ca_extract failed on window %u", w);
        if (status != 0) {
            continue;
        }

        for (uint32_t f = 0; f < v->n_features; ++f) {
            float difference = fabsf(computed[f] - expected[f]);
            float denominator = fabsf(expected[f]);
            if (denominator < FEATURE_ABS_FLOOR) {
                denominator = FEATURE_ABS_FLOOR;
            }
            float relative = difference / denominator;
            if (relative > worst_relative) {
                worst_relative = relative;
                worst_feature = (int)f;
                worst_window = (int)w;
            }
            if (relative > FEATURE_REL_TOL && difference > FEATURE_ABS_FLOOR) {
                if (mismatches < 10) {
                    fprintf(stderr,
                            "  window %u feature %u (%s): C %.6g vs Python %.6g "
                            "(rel %.2e)\n",
                            w, f,
                            f < (uint32_t)CA_N_FEATURES ? "" : "",
                            (double)computed[f], (double)expected[f],
                            (double)relative);
                }
                ++mismatches;
            }
        }
    }

    check(mismatches == 0, "%d feature values exceeded the tolerance", mismatches);
    printf("  worst relative error %.2e (window %d, feature %d)\n",
           (double)worst_relative, worst_window, worst_feature);
}

/* ---------------------------------------------------------------------- */
/* test: standardisation and forest match scikit-learn                    */
/* ---------------------------------------------------------------------- */

static void test_forest(const vectors_t *v, ca_scratch *scratch)
{
    printf("forest inference vs scikit-learn\n");

    static ca_real full[CA_FEATURE_COUNT];
    ca_real selected[CA_N_FEATURES];

    float worst_proba = 0.0f;
    int decision_mismatches = 0;

    for (uint32_t w = 0; w < v->n_windows; ++w) {
        const float *window = &v->windows[(size_t)w * v->width * v->n_channels];

        /* Part 1: run the forest on Python's own scaled features.  This
         * isolates the tree walk from any feature-extraction drift -- it must
         * agree essentially exactly. */
        const float *python_scaled = &v->scaled[(size_t)w * v->n_selected];
        ca_real from_python = ca_forest_predict(python_scaled);
        float difference = fabsf(from_python - v->proba[w]);
        check(difference < 1e-5f,
              "window %u: forest on Python features gave %.6f, sklearn %.6f", w,
              (double)from_python, (double)v->proba[w]);

        /* Part 2: the full on-device path, features and all. */
        ca_extract(window, v->width, v->fs_hz, scratch, full);
        ca_prepare_features(full, selected);
        ca_real end_to_end = ca_forest_predict(selected);

        float gap = fabsf(end_to_end - v->proba[w]);
        if (gap > worst_proba) {
            worst_proba = gap;
        }
        check(gap < PROBA_ABS_TOL,
              "window %u: end-to-end probability %.4f vs sklearn %.4f", w,
              (double)end_to_end, (double)v->proba[w]);

        bool device_says_spin = end_to_end >= CA_VOTE_THRESHOLD;
        bool python_says_spin = v->proba[w] >= CA_VOTE_THRESHOLD;
        if (device_says_spin != python_says_spin) {
            ++decision_mismatches;
            fprintf(stderr,
                    "  window %u: device %.4f vs python %.4f straddle the "
                    "%.2f vote threshold\n",
                    w, (double)end_to_end, (double)v->proba[w],
                    (double)CA_VOTE_THRESHOLD);
        }
    }

    check(decision_mismatches == 0,
          "%d windows would vote differently on-device", decision_mismatches);
    printf("  worst end-to-end probability difference %.2e\n", (double)worst_proba);
}

/* ---------------------------------------------------------------------- */
/* test: verification gate matches ml/tests/test_verification.py           */
/* ---------------------------------------------------------------------- */

static void test_verification(void)
{
    printf("verification gate vs ml/canine_alert/verification.py\n");
    ca_verify_gate gate;
    ca_alert alert;

    /* k of n: a single positive must not fire when k = 2. */
    ca_verify_init_with(&gate, 2, 3, 0.5f, 0u);
    check(!ca_verify_push(&gate, 0.99f, 0u, &alert), "single positive fired at k=2");
    check(ca_verify_push(&gate, 0.80f, 1300u, &alert), "second positive did not fire");
    check(alert.votes == 2, "expected 2 votes, got %d", alert.votes);
    check(alert.window_index == 1, "expected window_index 1, got %d",
          alert.window_index);
    check(fabsf(alert.confidence - 0.895f) < 1e-4f,
          "confidence %.4f should average only the voting windows",
          (double)alert.confidence);

    /* Non-consecutive positives still count inside the window. */
    ca_verify_init_with(&gate, 2, 3, 0.5f, 0u);
    check(!ca_verify_push(&gate, 0.9f, 0u, &alert), "unexpected fire 1");
    check(!ca_verify_push(&gate, 0.1f, 1300u, &alert), "unexpected fire 2");
    check(ca_verify_push(&gate, 0.9f, 2600u, &alert), "2-of-3 did not fire");

    /* Positives further apart than n must not accumulate. */
    ca_verify_init_with(&gate, 2, 3, 0.5f, 0u);
    ca_verify_push(&gate, 0.9f, 0u, &alert);
    ca_verify_push(&gate, 0.1f, 1300u, &alert);
    ca_verify_push(&gate, 0.1f, 2600u, &alert);
    check(!ca_verify_push(&gate, 0.9f, 3900u, &alert),
          "an aged-out positive still counted");

    /* Threshold comparison is inclusive. */
    ca_verify_init_with(&gate, 1, 1, 0.45f, 0u);
    check(ca_verify_push(&gate, 0.45f, 0u, &alert), "p == threshold did not vote");
    ca_verify_init_with(&gate, 1, 1, 0.45f, 0u);
    check(!ca_verify_push(&gate, 0.4499f, 0u, &alert), "p < threshold voted");

    /* Refractory period suppresses, then releases. */
    ca_verify_init_with(&gate, 1, 1, 0.5f, 60000u);
    check(ca_verify_push(&gate, 0.9f, 1000u, &alert), "first alert did not fire");
    check(!ca_verify_push(&gate, 0.9f, 30000u, &alert), "refractory did not suppress");
    check(!ca_verify_push(&gate, 0.9f, 60999u, &alert), "refractory released early");
    check(ca_verify_push(&gate, 0.9f, 61000u, &alert), "refractory never released");

    /* Evidence is cleared after firing: k fresh votes are needed. */
    ca_verify_init_with(&gate, 2, 3, 0.5f, 10000u);
    ca_verify_push(&gate, 0.9f, 0u, &alert);
    check(ca_verify_push(&gate, 0.9f, 1300u, &alert), "did not fire at k=2");
    check(!ca_verify_push(&gate, 0.9f, 11300u, &alert), "re-fired on stale evidence");
    check(ca_verify_push(&gate, 0.9f, 12600u, &alert), "did not re-arm");

    /* millis() wraps every 49.7 days; the refractory maths must survive it. */
    ca_verify_init_with(&gate, 1, 1, 0.5f, 60000u);
    uint32_t before_wrap = 0xFFFFFFFFu - 5000u;
    check(ca_verify_push(&gate, 0.9f, before_wrap, &alert), "pre-wrap alert failed");
    check(!ca_verify_push(&gate, 0.9f, before_wrap + 30000u, &alert),
          "refractory broke across the millis() wrap");
    check(ca_verify_push(&gate, 0.9f, before_wrap + 60000u, &alert),
          "refractory never released across the wrap");

    /* Invalid policies are rejected rather than silently accepted. */
    check(!ca_verify_init_with(&gate, 4, 2, 0.5f, 0u), "accepted k > n");
    check(!ca_verify_init_with(&gate, 0, 2, 0.5f, 0u), "accepted k < 1");
    check(!ca_verify_init_with(&gate, 1, CA_VERIFY_MAX_N + 1, 0.5f, 0u),
          "accepted n > CA_VERIFY_MAX_N");

    /* The compiled-in defaults must be the ones the evaluation selected. */
    ca_verify_init(&gate);
    check(gate.k == CA_VERIFY_K && gate.n == CA_VERIFY_N,
          "default policy is not the exported one");
}

/* ---------------------------------------------------------------------- */
/* test: degenerate inputs                                                */
/* ---------------------------------------------------------------------- */

static void test_degenerate_inputs(ca_scratch *scratch)
{
    printf("degenerate inputs\n");
    static ca_real out[CA_FEATURE_COUNT];
    static ca_real window[CA_WINDOW_SAMPLES * CA_N_CHANNELS];

    /* A collar lying still on a table: every channel constant.  Skew and
     * kurtosis divide by the standard deviation, so this is where a naive port
     * produces NaN and then walks an arbitrary path through the forest. */
    for (int i = 0; i < CA_WINDOW_SAMPLES * CA_N_CHANNELS; ++i) {
        window[i] = (i % CA_N_CHANNELS == 2) ? 9.81f : 0.0f;
    }
    check(ca_extract(window, CA_WINDOW_SAMPLES, CA_SAMPLE_RATE_HZ, scratch, out) == 0,
          "ca_extract rejected a constant window");
    for (int f = 0; f < CA_FEATURE_COUNT; ++f) {
        if (!isfinite(out[f])) {
            check(false, "feature %d is not finite for a constant window", f);
            break;
        }
    }
    ++checks; /* the loop above only reports on failure */

    ca_real selected[CA_N_FEATURES];
    ca_prepare_features(out, selected);
    ca_real probability = ca_forest_predict(selected);
    check(probability >= 0.0f && probability <= 1.0f,
          "probability %.4f out of range for a constant window",
          (double)probability);

    /* Oversized window must be refused, not overflow the scratch buffers. */
    check(ca_extract(window, CA_MAX_WINDOW + 1, CA_SAMPLE_RATE_HZ, scratch, out) == -1,
          "ca_extract accepted an oversized window");
    check(ca_extract(window, 0, CA_SAMPLE_RATE_HZ, scratch, out) == -1,
          "ca_extract accepted an empty window");
}

/* ---------------------------------------------------------------------- */
/* test: sample ring                                                       */
/* ---------------------------------------------------------------------- */

static void test_ring(void)
{
    printf("sample ring\n");
    static ca_ring ring;
    static ca_real window[CA_WINDOW_SAMPLES * CA_N_CHANNELS];
    ca_real sample[CA_N_CHANNELS];

    ca_ring_init(&ring);
    check(!ca_ring_ready(&ring), "empty ring reported ready");
    check(!ca_ring_copy_window(&ring, window), "empty ring yielded a window");

    /* Fill one window short of full. */
    for (int i = 0; i < CA_WINDOW_SAMPLES - 1; ++i) {
        for (int c = 0; c < CA_N_CHANNELS; ++c) {
            sample[c] = (ca_real)(i * 10 + c);
        }
        ca_ring_push(&ring, sample);
    }
    check(!ca_ring_ready(&ring), "ring reported ready one sample early");

    for (int c = 0; c < CA_N_CHANNELS; ++c) {
        sample[c] = (ca_real)((CA_WINDOW_SAMPLES - 1) * 10 + c);
    }
    ca_ring_push(&ring, sample);
    check(ca_ring_ready(&ring), "full ring did not report ready");
    check(ca_ring_copy_window(&ring, window), "full ring refused to copy");

    /* The copy must be in chronological order, oldest first. */
    bool ordered = true;
    for (int i = 0; i < CA_WINDOW_SAMPLES && ordered; ++i) {
        for (int c = 0; c < CA_N_CHANNELS; ++c) {
            if (fabsf(window[i * CA_N_CHANNELS + c] - (ca_real)(i * 10 + c)) > 1e-3f) {
                ordered = false;
                break;
            }
        }
    }
    check(ordered, "window samples were out of order or wrong");

    /* Push far past the capacity: the window must still be the newest samples,
     * correctly unwrapped. */
    for (int i = CA_WINDOW_SAMPLES; i < CA_WINDOW_SAMPLES + 5 * CA_RING_CAPACITY; ++i) {
        for (int c = 0; c < CA_N_CHANNELS; ++c) {
            sample[c] = (ca_real)(i * 10 + c);
        }
        ca_ring_push(&ring, sample);
    }
    check(ca_ring_copy_window(&ring, window), "wrapped ring refused to copy");

    int newest = CA_WINDOW_SAMPLES + 5 * CA_RING_CAPACITY - 1;
    int oldest = newest - CA_WINDOW_SAMPLES + 1;
    check(fabsf(window[0] - (ca_real)(oldest * 10)) < 1e-3f,
          "oldest sample after wrap was %g, expected %g", (double)window[0],
          (double)(oldest * 10));
    check(fabsf(window[(CA_WINDOW_SAMPLES - 1) * CA_N_CHANNELS] -
                (ca_real)(newest * 10)) < 1e-3f,
          "newest sample after wrap was wrong");
}

/* ---------------------------------------------------------------------- */

int main(int argc, char **argv)
{
    const char *path = (argc > 1) ? argv[1] : "vectors.bin";

    vectors_t vectors;
    memset(&vectors, 0, sizeof(vectors));
    if (!load_vectors(path, &vectors)) {
        fprintf(stderr,
                "\nGenerate the vectors first:\n"
                "  python ml/scripts/make_firmware_vectors.py\n");
        return 2;
    }

    printf("collar core tests -- %u golden windows from the real dataset\n\n",
           vectors.n_windows);

    /* Static rather than automatic: ca_scratch is ~12 kB, which is more than a
     * default FreeRTOS task stack and more than some host defaults too. */
    static ca_scratch scratch;

    test_geometry(&vectors);
    test_features(&vectors, &scratch);
    test_forest(&vectors, &scratch);
    test_verification();
    test_ring();
    test_degenerate_inputs(&scratch);

    free_vectors(&vectors);

    printf("\n%d checks, %d failures\n", checks, failures);
    if (failures == 0) {
        printf("PASS\n");
        return 0;
    }
    printf("FAIL\n");
    return 1;
}
