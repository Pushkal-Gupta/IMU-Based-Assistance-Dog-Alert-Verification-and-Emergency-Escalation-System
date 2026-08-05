/* Fixed-capacity sample ring for the IMU stream.
 *
 * The sampling task writes one 6-channel sample every 1/fs seconds; the
 * inference task periodically copies out the most recent CA_WINDOW_SAMPLES as a
 * contiguous block.  Capacity is one window plus one stride, so a window can
 * always be assembled without blocking the sampler.
 *
 * Single-producer / single-consumer.  The producer only advances `write_index`
 * and the consumer only reads it, so on a 32-bit core with aligned words no
 * lock is needed for the index itself -- but a window copied while the producer
 * wraps could mix old and new samples, so ca_ring_copy_window() re-checks the
 * write index after copying and reports a tear rather than returning corrupt
 * data.  The caller simply retries.
 */

#ifndef CA_RING_H
#define CA_RING_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "ca_features.h"
#include "model.h"

#ifdef __cplusplus
extern "C" {
#endif

#define CA_RING_CAPACITY (CA_WINDOW_SAMPLES + CA_STRIDE_SAMPLES)

typedef struct {
    ca_real samples[CA_RING_CAPACITY][CA_N_CHANNELS];
    volatile uint32_t write_index; /* monotonic count of samples ever written */
} ca_ring;

void ca_ring_init(ca_ring *ring);

/* Append one sample.  `channels` must hold CA_N_CHANNELS values in the order
 * ax, ay, az, gx, gy, gz. */
void ca_ring_push(ca_ring *ring, const ca_real *channels);

/* True once at least one full window has been collected. */
bool ca_ring_ready(const ca_ring *ring);

/* Copy the newest CA_WINDOW_SAMPLES into `out` (row-major).
 *
 * Returns false if the producer wrapped past the region mid-copy (a tear) or
 * if fewer than a window's worth of samples exist yet.  A false return is not
 * an error -- retry on the next iteration.
 */
bool ca_ring_copy_window(const ca_ring *ring, ca_real *out);

#ifdef __cplusplus
}
#endif

#endif /* CA_RING_H */
