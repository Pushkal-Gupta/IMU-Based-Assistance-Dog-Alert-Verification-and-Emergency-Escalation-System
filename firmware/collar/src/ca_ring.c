/* Sample ring -- see ca_ring.h. */

#include "ca_ring.h"

#include <string.h>

void ca_ring_init(ca_ring *ring)
{
    memset(ring->samples, 0, sizeof(ring->samples));
    ring->write_index = 0u;
}

void ca_ring_push(ca_ring *ring, const ca_real *channels)
{
    uint32_t slot = ring->write_index % CA_RING_CAPACITY;
    for (size_t c = 0; c < CA_N_CHANNELS; ++c) {
        ring->samples[slot][c] = channels[c];
    }
    /* Publish the sample only after its data is written, so a consumer that
     * observes the new index always sees complete data in that slot. */
    ring->write_index = ring->write_index + 1u;
}

bool ca_ring_ready(const ca_ring *ring)
{
    return ring->write_index >= (uint32_t)CA_WINDOW_SAMPLES;
}

bool ca_ring_copy_window(const ca_ring *ring, ca_real *out)
{
    uint32_t start_index = ring->write_index;
    if (start_index < (uint32_t)CA_WINDOW_SAMPLES) {
        return false;
    }

    uint32_t first = start_index - (uint32_t)CA_WINDOW_SAMPLES;
    for (size_t i = 0; i < (size_t)CA_WINDOW_SAMPLES; ++i) {
        uint32_t slot = (first + (uint32_t)i) % CA_RING_CAPACITY;
        for (size_t c = 0; c < CA_N_CHANNELS; ++c) {
            out[i * CA_N_CHANNELS + c] = ring->samples[slot][c];
        }
    }

    /* If the producer has written a whole stride's worth since we started, the
     * oldest samples we copied have been overwritten and the window is torn.
     * Report it instead of handing the classifier a spliced window. */
    uint32_t written_during_copy = ring->write_index - start_index;
    return written_during_copy < (uint32_t)CA_STRIDE_SAMPLES;
}
