/* Host micro-benchmark of the collar's per-window work.
 *
 * Measures, on whatever machine runs it, the time to turn one 133 x 6 window
 * into a spin probability: feature extraction, standardisation and the forest
 * walk.  It also counts what does not depend on the machine -- forest node
 * visits per window and transcendental calls per window -- because those are
 * what an ESP32 estimate has to be built from.  The host time is NOT an ESP32
 * time and is never reported as one.
 *
 *   make bench          writes bench.json (twiddle-table DFT, the shipped one)
 *   make bench-direct   the same with the old in-loop cosf/sinf DFT
 */
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

#include "../collar/src/ca_features.h"
#include "../collar/src/ca_forest.h"
#include "../collar/src/model.h"

#ifndef BENCH_ITERATIONS
#define BENCH_ITERATIONS 2000
#endif
#ifndef BENCH_REPEATS
#define BENCH_REPEATS 7
#endif

static double now_s(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec * 1e-9;
}

/* A plausible window: gravity on one axis, a 1 Hz body sway, and a spin-like
 * burst of high yaw rate, plus deterministic pseudo-noise. */
static void synth_window(ca_real *w, unsigned seed)
{
    uint32_t state = 2463534242u ^ seed;
    for (int i = 0; i < CA_WINDOW_SAMPLES; ++i) {
        double t = (double)i / CA_SAMPLE_RATE_HZ;
        state ^= state << 13; state ^= state >> 17; state ^= state << 5;
        double noise = ((double)(state % 1000u) / 1000.0 - 0.5);
        w[i * 6 + 0] = (ca_real)(0.8 * sin(2.0 * M_PI * 1.0 * t) + 0.2 * noise);
        w[i * 6 + 1] = (ca_real)(0.5 * cos(2.0 * M_PI * 0.7 * t) + 0.2 * noise);
        w[i * 6 + 2] = (ca_real)(9.81 + 0.4 * noise);
        w[i * 6 + 3] = (ca_real)(30.0 * noise);
        w[i * 6 + 4] = (ca_real)(40.0 * sin(2.0 * M_PI * 2.0 * t));
        w[i * 6 + 5] = (ca_real)(((seed % 2u) ? 380.0 : 20.0) * sin(M_PI * t / 2.6) + 10.0 * noise);
    }
}

static long count_visits(const ca_real *features)
{
    long visits = 0;
    for (int t = 0; t < CA_N_TREES; ++t) {
        int node = ca_tree_offset[t];
        while (ca_node_feature[node] >= 0) {
            ++visits;
            node = (features[ca_node_feature[node]] <= ca_node_threshold[node]) ? ca_node_left[node]
                                                                                 : ca_node_right[node];
        }
        ++visits;
    }
    return visits;
}

int main(int argc, char **argv)
{
    const char *out_path = argc > 1 ? argv[1] : "bench.json";
    static ca_scratch scratch;
    static ca_real windows[16][CA_WINDOW_SAMPLES * 6];
    ca_real full[CA_FEATURE_COUNT];
    ca_real selected[CA_N_FEATURES];
    for (unsigned s = 0; s < 16u; ++s) {
        synth_window(windows[s], s);
    }

    /* warm-up, and the twiddle table build */
    volatile ca_real sink = 0.0f;
    for (int i = 0; i < 50; ++i) {
        ca_extract(windows[i % 16], CA_WINDOW_SAMPLES, CA_SAMPLE_RATE_HZ, &scratch, full);
    }

    /* Minimum over repeats: the host may be shared, and the minimum is the
     * estimate least contaminated by other load. */
    double t_extract = 1e9, t_total = 1e9, t_forest = 1e9, t0;
    for (int rep = 0; rep < BENCH_REPEATS; ++rep) {
        t0 = now_s();
        for (int i = 0; i < BENCH_ITERATIONS; ++i) {
            ca_extract(windows[i % 16], CA_WINDOW_SAMPLES, CA_SAMPLE_RATE_HZ, &scratch, full);
            sink += full[i % CA_FEATURE_COUNT];
        }
        double t = (now_s() - t0) / BENCH_ITERATIONS;
        t_extract = t < t_extract ? t : t_extract;

        t0 = now_s();
        for (int i = 0; i < BENCH_ITERATIONS; ++i) {
            ca_extract(windows[i % 16], CA_WINDOW_SAMPLES, CA_SAMPLE_RATE_HZ, &scratch, full);
            ca_prepare_features(full, selected);
            sink += ca_forest_predict(selected);
        }
        t = (now_s() - t0) / BENCH_ITERATIONS;
        t_total = t < t_total ? t : t_total;
    }

    long visits = 0;

    for (int i = 0; i < 16; ++i) {
        ca_extract(windows[i], CA_WINDOW_SAMPLES, CA_SAMPLE_RATE_HZ, &scratch, full);
        ca_prepare_features(full, selected);
        visits += count_visits(selected);
    }
    for (int rep = 0; rep < BENCH_REPEATS; ++rep) {
        t0 = now_s();
        for (int i = 0; i < BENCH_ITERATIONS * 10; ++i) {
            sink += ca_forest_predict(selected);
        }
        double t = (now_s() - t0) / (BENCH_ITERATIONS * 10);
        t_forest = t < t_forest ? t : t_forest;
    }

    const long n = CA_WINDOW_SAMPLES;
    const long bins = n / 2;
#ifdef CA_DFT_DIRECT_TRIG
    const long trig_calls = 2L * bins * n * CA_N_SIGNALS;
    const char *variant = "direct_trig";
#else
    const long trig_calls = 0L; /* table built once, outside the window loop */
    const char *variant = "twiddle_table";
#endif
    const long dft_macs = 2L * bins * n * CA_N_SIGNALS;
    const long sort_compares = (long)CA_N_SIGNALS * n * (n - 1) / 2; /* insertion sort, worst case */

    FILE *f = fopen(out_path, "w");
    if (!f) {
        perror(out_path);
        return 1;
    }
    fprintf(f,
            "{\n  \"variant\": \"%s\",\n  \"iterations\": %d,\n  \"repeats\": %d,\n"
            "  \"host_us_per_window_extract\": %.3f,\n"
            "  \"host_us_per_window_total\": %.3f,\n"
            "  \"host_us_per_forest_predict\": %.4f,\n"
            "  \"window_samples\": %d,\n  \"n_trees\": %d,\n  \"n_nodes\": %d,\n"
            "  \"mean_node_visits_per_window\": %.1f,\n"
            "  \"dft_real_macs_per_window\": %ld,\n"
            "  \"transcendental_calls_per_window_in_dft\": %ld,\n"
            "  \"sort_compares_per_window_worst\": %ld,\n"
            "  \"scratch_bytes\": %zu,\n"
            "  \"stride_seconds\": %.4f\n}\n",
            variant, BENCH_ITERATIONS, BENCH_REPEATS, t_extract * 1e6, t_total * 1e6, t_forest * 1e6,
            CA_WINDOW_SAMPLES, CA_N_TREES, CA_N_NODES, (double)visits / 16.0, dft_macs, trig_calls,
            sort_compares, sizeof(ca_scratch), (double)CA_STRIDE_SAMPLES / CA_SAMPLE_RATE_HZ);
    fclose(f);
    printf("%s: %.1f us/window total (%.1f extract, %.3f forest), %.0f node visits\n", variant,
           t_total * 1e6, t_extract * 1e6, t_forest * 1e6, (double)visits / 16.0);
    return sink == 12345.0f ? 2 : 0;
}
