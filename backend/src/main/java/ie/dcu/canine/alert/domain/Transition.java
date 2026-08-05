package ie.dcu.canine.alert.domain;

import jakarta.json.bind.annotation.JsonbProperty;

/**
 * One entry in an alert's audit trail.
 *
 * <p>Every transition carries a human-readable reason. When a caregiver asks
 * afterwards why they were called at 3am, "PENDING_CAREGIVER" is not an answer
 * and "owner did not respond within 60s" is.
 */
public class Transition {

    @JsonbProperty("at_seconds")
    private double atSeconds;

    @JsonbProperty("from_state")
    private AlertState fromState;

    @JsonbProperty("to_state")
    private AlertState toState;

    private String reason;

    public Transition() {
        // Required by JSON-B.
    }

    public Transition(double atSeconds, AlertState fromState, AlertState toState, String reason) {
        this.atSeconds = atSeconds;
        this.fromState = fromState;
        this.toState = toState;
        this.reason = reason;
    }

    public double getAtSeconds() {
        return atSeconds;
    }

    public void setAtSeconds(double atSeconds) {
        this.atSeconds = atSeconds;
    }

    public AlertState getFromState() {
        return fromState;
    }

    public void setFromState(AlertState fromState) {
        this.fromState = fromState;
    }

    public AlertState getToState() {
        return toState;
    }

    public void setToState(AlertState toState) {
        this.toState = toState;
    }

    public String getReason() {
        return reason;
    }

    public void setReason(String reason) {
        this.reason = reason;
    }
}
