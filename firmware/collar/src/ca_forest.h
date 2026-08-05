/* Random forest inference over the tables generated into model.h.
 *
 * Portable C, no Arduino dependency, so the host test can run it.
 */

#ifndef CA_FOREST_H
#define CA_FOREST_H

#include "ca_features.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Gather the selected features from the full vector and standardise them.
 *
 * `full` holds CA_FEATURE_COUNT values from ca_extract(); `out` receives
 * CA_N_FEATURES standardised values ready for ca_forest_predict().
 */
void ca_prepare_features(const ca_real *full, ca_real *out);

/* P(spin) for one standardised feature vector: the mean of the per-tree leaf
 * probabilities, which is what scikit-learn's predict_proba computes. */
ca_real ca_forest_predict(const ca_real *features);

/* Convenience: extract, standardise and classify in one call. */
ca_real ca_classify_window(const ca_real *window, ca_scratch *scratch,
                           ca_real *feature_workspace);

#ifdef __cplusplus
}
#endif

#endif /* CA_FOREST_H */
