/* Multi-stage verification gate -- C port of ml/canine_alert/verification.py.
 *
 * A single positive window is not an alert.  The gate requires CA_VERIFY_K of
 * the last CA_VERIFY_N windows to vote 'spin', then suppresses further alerts
 * for CA_REFRACTORY_MS so that one behavioural episode produces exactly one
 * escalation.
 *
 * Portable C; the host test runs the same cases as ml/tests/test_verification.py.
 */

#ifndef CA_VERIFY_H
#define CA_VERIFY_H

#include <stdbool.h>
#include <stdint.h>

#include "ca_features.h"

#ifdef __cplusplus
extern "C" {
#endif

#define CA_VERIFY_MAX_N 8

typedef struct {
    int k;
    int n;
    ca_real vote_threshold;
    uint32_t refractory_ms;

    /* Circular buffer of the last n windows. */
    uint8_t votes[CA_VERIFY_MAX_N];
    ca_real probabilities[CA_VERIFY_MAX_N];
    int count;  /* how many slots are filled, <= n */
    int head;   /* next slot to write */

    int32_t window_index;      /* -1 before the first window */
    bool has_fired;            /* whether last_alert_ms is meaningful */
    uint32_t last_alert_ms;
} ca_verify_gate;

typedef struct {
    uint32_t timestamp_ms;
    int32_t window_index;
    ca_real confidence; /* mean probability of the voting windows */
    int votes;
    int window_count;
} ca_alert;

/* Initialise with the compiled-in policy from model.h. */
void ca_verify_init(ca_verify_gate *gate);

/* Initialise with an explicit policy.  Returns false if k/n are out of range,
 * in which case the gate is left in its compiled-in default. */
bool ca_verify_init_with(ca_verify_gate *gate, int k, int n,
                         ca_real vote_threshold, uint32_t refractory_ms);

void ca_verify_reset(ca_verify_gate *gate);

/* Feed one window's probability.  Returns true and fills `out` when the vote
 * completes and the refractory period has elapsed. */
bool ca_verify_push(ca_verify_gate *gate, ca_real probability,
                    uint32_t timestamp_ms, ca_alert *out);

#ifdef __cplusplus
}
#endif

#endif /* CA_VERIFY_H */
