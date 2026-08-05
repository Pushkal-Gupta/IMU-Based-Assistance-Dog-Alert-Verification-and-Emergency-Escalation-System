package ie.dcu.canine.alert.domain;

import jakarta.json.bind.annotation.JsonbProperty;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;

/**
 * One alert episode as stored by the backend.
 *
 * <p>The relay is the source of truth for an alert's <em>state</em>; this record
 * is the durable copy. It is written by upsert keyed on {@link #alertId}, so a
 * relay flushing a backlog after an outage replays safely and a BLE
 * retransmission cannot create a second row.
 *
 * <p>Two clocks appear here, on purpose. {@code raisedAtSeconds} comes from the
 * relay's <em>monotonic</em> clock -- it has no epoch, and is the only timebase
 * in which the escalation intervals are meaningful, because a wall clock that
 * jumps during an alert would corrupt them. {@code receivedAt} is the backend's
 * wall clock, used for retention and for ordering across relays. Never subtract
 * one from the other.
 */
public class AlertRecord {

    @JsonbProperty("alert_id")
    private String alertId;

    @JsonbProperty("dog_id")
    private String dogId;

    @JsonbProperty("raised_at_seconds")
    private double raisedAtSeconds;

    private double confidence;

    private AlertState state;

    private Location location;

    @JsonbProperty("owner_response_seconds")
    private Double ownerResponseSeconds;

    @JsonbProperty("escalated_by_watchdog")
    private boolean escalatedByWatchdog;

    private List<Transition> transitions = new ArrayList<>();

    private List<NotificationAttempt> notifications = new ArrayList<>();

    /** Backend wall-clock arrival time; not part of the relay's payload. */
    @JsonbProperty("received_at")
    private Instant receivedAt = Instant.now();

    public AlertRecord() {
        // Required by JSON-B.
    }

    // -- accessors --------------------------------------------------------- //
    public String getAlertId() {
        return alertId;
    }

    public void setAlertId(String alertId) {
        this.alertId = alertId;
    }

    public String getDogId() {
        return dogId;
    }

    public void setDogId(String dogId) {
        this.dogId = dogId;
    }

    public double getRaisedAtSeconds() {
        return raisedAtSeconds;
    }

    public void setRaisedAtSeconds(double raisedAtSeconds) {
        this.raisedAtSeconds = raisedAtSeconds;
    }

    public double getConfidence() {
        return confidence;
    }

    public void setConfidence(double confidence) {
        this.confidence = confidence;
    }

    public AlertState getState() {
        return state;
    }

    public void setState(AlertState state) {
        this.state = state;
    }

    public Location getLocation() {
        return location;
    }

    public void setLocation(Location location) {
        this.location = location;
    }

    public Double getOwnerResponseSeconds() {
        return ownerResponseSeconds;
    }

    public void setOwnerResponseSeconds(Double ownerResponseSeconds) {
        this.ownerResponseSeconds = ownerResponseSeconds;
    }

    public boolean isEscalatedByWatchdog() {
        return escalatedByWatchdog;
    }

    public void setEscalatedByWatchdog(boolean escalatedByWatchdog) {
        this.escalatedByWatchdog = escalatedByWatchdog;
    }

    public List<Transition> getTransitions() {
        return transitions;
    }

    public void setTransitions(List<Transition> transitions) {
        this.transitions = transitions == null ? new ArrayList<>() : transitions;
    }

    public List<NotificationAttempt> getNotifications() {
        return notifications;
    }

    public void setNotifications(List<NotificationAttempt> notifications) {
        this.notifications = notifications == null ? new ArrayList<>() : notifications;
    }

    public Instant getReceivedAt() {
        return receivedAt;
    }

    public void setReceivedAt(Instant receivedAt) {
        this.receivedAt = receivedAt;
    }

    // -- behaviour --------------------------------------------------------- //

    /** True when a human beyond the owner has already been paged. */
    public boolean reachedBeyondOwner() {
        return notifications.stream()
                .anyMatch(n -> n.isDelivered()
                        && (Channel.CAREGIVER == n.getChannel() || Channel.EMERGENCY == n.getChannel()));
    }

    /**
     * Records a state change made by the backend itself, as the watchdog does.
     * Relay-driven changes arrive already carrying their transitions.
     */
    public void recordTransition(AlertState to, String reason, double atSeconds) {
        transitions.add(new Transition(atSeconds, state, to, reason));
        state = to;
    }
}
