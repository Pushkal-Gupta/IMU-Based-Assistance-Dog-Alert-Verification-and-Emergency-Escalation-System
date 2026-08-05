/* Multi-stage verification gate -- see ca_verify.h. */

#include "ca_verify.h"

#include <string.h>

#include "model.h"

void ca_verify_reset(ca_verify_gate *gate)
{
    memset(gate->votes, 0, sizeof(gate->votes));
    memset(gate->probabilities, 0, sizeof(gate->probabilities));
    gate->count = 0;
    gate->head = 0;
    gate->window_index = -1;
    gate->has_fired = false;
    gate->last_alert_ms = 0u;
}

bool ca_verify_init_with(ca_verify_gate *gate, int k, int n,
                         ca_real vote_threshold, uint32_t refractory_ms)
{
    if (k < 1 || n < k || n > CA_VERIFY_MAX_N) {
        ca_verify_init(gate);
        return false;
    }
    gate->k = k;
    gate->n = n;
    gate->vote_threshold = vote_threshold;
    gate->refractory_ms = refractory_ms;
    ca_verify_reset(gate);
    return true;
}

void ca_verify_init(ca_verify_gate *gate)
{
    gate->k = CA_VERIFY_K;
    gate->n = CA_VERIFY_N;
    gate->vote_threshold = CA_VOTE_THRESHOLD;
    gate->refractory_ms = CA_REFRACTORY_MS;
    ca_verify_reset(gate);
}

bool ca_verify_push(ca_verify_gate *gate, ca_real probability,
                    uint32_t timestamp_ms, ca_alert *out)
{
    ++gate->window_index;

    /* The threshold comparison is >=, matching verification.py, so a
     * probability exactly equal to the threshold does vote. */
    gate->votes[gate->head] = (probability >= gate->vote_threshold) ? 1u : 0u;
    gate->probabilities[gate->head] = probability;
    gate->head = (gate->head + 1) % gate->n;
    if (gate->count < gate->n) {
        ++gate->count;
    }

    int positive = 0;
    ca_real sum = 0.0f;
    for (int i = 0; i < gate->count; ++i) {
        if (gate->votes[i]) {
            ++positive;
            sum += gate->probabilities[i];
        }
    }

    if (positive < gate->k) {
        return false;
    }

    if (gate->has_fired) {
        /* Unsigned subtraction is correct across the 49.7-day millis() wrap:
         * the difference stays right as long as the interval itself fits in
         * uint32, which a 60 s refractory comfortably does. */
        uint32_t since = timestamp_ms - gate->last_alert_ms;
        if (since < gate->refractory_ms) {
            return false;
        }
    }

    if (out != NULL) {
        out->timestamp_ms = timestamp_ms;
        out->window_index = gate->window_index;
        out->confidence = (positive > 0) ? sum / (ca_real)positive : 0.0f;
        out->votes = positive;
        out->window_count = gate->count;
    }

    gate->last_alert_ms = timestamp_ms;
    gate->has_fired = true;

    /* Clear the evidence so the next alert needs k *fresh* votes.  Without
     * this the gate re-fires off the same windows the instant the refractory
     * period ends, which would turn one episode into a repeating page. */
    memset(gate->votes, 0, sizeof(gate->votes));
    memset(gate->probabilities, 0, sizeof(gate->probabilities));
    gate->count = 0;
    gate->head = 0;

    return true;
}
