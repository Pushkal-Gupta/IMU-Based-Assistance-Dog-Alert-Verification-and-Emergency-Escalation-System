package ie.dcu.canine.alert.domain;

import jakarta.json.bind.annotation.JsonbProperty;

import java.time.Duration;
import java.time.Instant;

/**
 * Liveness report from an owner's relay.
 *
 * <p>This is what lets the backend cover the failure mode a phone-only design
 * cannot: the owner's handset dies, is switched off, or loses power mid-alert.
 * Without a heartbeat the alert would simply stop advancing and nobody would
 * ever be paged. See {@code EscalationWatchdog}.
 */
public class RelayHeartbeat {

    @JsonbProperty("relay_id")
    private String relayId;

    @JsonbProperty("dog_id")
    private String dogId;

    @JsonbProperty("open_alerts")
    private int openAlerts;

    @JsonbProperty("received_at")
    private Instant receivedAt = Instant.now();

    public RelayHeartbeat() {
        // Required by JSON-B.
    }

    public String getRelayId() {
        return relayId;
    }

    public void setRelayId(String relayId) {
        this.relayId = relayId;
    }

    public String getDogId() {
        return dogId;
    }

    public void setDogId(String dogId) {
        this.dogId = dogId;
    }

    public int getOpenAlerts() {
        return openAlerts;
    }

    public void setOpenAlerts(int openAlerts) {
        this.openAlerts = openAlerts;
    }

    public Instant getReceivedAt() {
        return receivedAt;
    }

    public void setReceivedAt(Instant receivedAt) {
        this.receivedAt = receivedAt;
    }

    public boolean isStale(Duration limit, Instant now) {
        return Duration.between(receivedAt, now).compareTo(limit) > 0;
    }
}
