package ie.dcu.canine.alert.domain;

/**
 * Lifecycle states of one alert episode.
 *
 * <p>Mirrors {@code escalation.model.AlertState} in the Python reference
 * implementation. The two must stay in step: the relay sends these names as
 * strings and the dashboard renders them, so adding a state here without adding
 * it there produces an alert nobody can interpret.
 *
 * <p>The terminal states are deliberately distinct rather than a single CLOSED.
 * A caregiver reviewing the log needs to see <em>who</em> closed each alert:
 * "the owner said they were fine" and "nobody answered and we called the
 * emergency contact" are the two outcomes the whole system exists to separate.
 */
public enum AlertState {

    /** Raised by the collar, waiting for the owner. */
    PENDING_OWNER(false),

    /** Owner window elapsed; the caregiver has been paged and has not replied. */
    PENDING_CAREGIVER(false),

    /** Owner acknowledged in time -- they are conscious and responding. */
    ACKNOWLEDGED_BY_OWNER(true),

    /** Caregiver acknowledged after the owner did not. */
    ACKNOWLEDGED_BY_CAREGIVER(true),

    /** Both windows elapsed; the emergency contact has been notified. */
    ESCALATED_EMERGENCY(true),

    /**
     * Owner marked it a false positive. Kept separate from an acknowledgement so
     * the training-quality statistics are not polluted by dismissals.
     */
    DISMISSED_FALSE_POSITIVE(true),

    /** Cancelled before any human beyond the owner was paged. */
    CANCELLED(true);

    private final boolean terminal;

    AlertState(boolean terminal) {
        this.terminal = terminal;
    }

    public boolean isTerminal() {
        return terminal;
    }

    public boolean isOpen() {
        return !terminal;
    }
}
