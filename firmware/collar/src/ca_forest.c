/* Random forest inference -- see ca_forest.h. */

#include "ca_forest.h"

#include "model.h"

void ca_prepare_features(const ca_real *full, ca_real *out)
{
    for (int i = 0; i < CA_N_FEATURES; ++i) {
        ca_real raw = full[ca_feature_index[i]];
        /* StandardScaler never emits a zero scale -- it substitutes 1.0 for a
         * constant feature -- so no guard is needed here. */
        out[i] = (raw - ca_feature_mean[i]) / ca_feature_scale[i];
    }
}

ca_real ca_forest_predict(const ca_real *features)
{
    ca_real total = 0.0f;

    for (int t = 0; t < CA_N_TREES; ++t) {
        int node = ca_tree_offset[t];
        /* Leaves are marked with a feature index of -1.  Children are absolute
         * indices into the shared node array and always exceed their parent's
         * index, so the walk terminates without a visited set. */
        while (ca_node_feature[node] >= 0) {
            if (features[ca_node_feature[node]] <= ca_node_threshold[node]) {
                node = ca_node_left[node];
            } else {
                node = ca_node_right[node];
            }
        }
        total += ca_node_value[node];
    }

    return total / (ca_real)CA_N_TREES;
}

ca_real ca_classify_window(const ca_real *window, ca_scratch *scratch,
                           ca_real *feature_workspace)
{
    ca_real selected[CA_N_FEATURES];

    if (ca_extract(window, CA_WINDOW_SAMPLES, CA_SAMPLE_RATE_HZ, scratch,
                   feature_workspace) != 0) {
        /* Refusing to guess: an unclassifiable window votes 'no spin' rather
         * than contributing a fabricated probability to the verification gate. */
        return 0.0f;
    }
    ca_prepare_features(feature_workspace, selected);
    return ca_forest_predict(selected);
}
