package ie.dcu.canine.alert.domain;

import jakarta.json.bind.annotation.JsonbProperty;

/**
 * One delivery attempt, recorded whether or not it succeeded.
 *
 * <p>Failures are kept, not discarded: "we tried to reach the caregiver and
 * could not" is exactly the fact an incident review needs, and it is invisible
 * if only successes are stored.
 */
public class NotificationAttempt {

    private Channel channel;

    @JsonbProperty("contact_id")
    private String contactId;

    private int attempt;

    @JsonbProperty("at_seconds")
    private double atSeconds;

    private DeliveryStatus status;

    private String detail = "";

    public NotificationAttempt() {
        // Required by JSON-B.
    }

    public Channel getChannel() {
        return channel;
    }

    public void setChannel(Channel channel) {
        this.channel = channel;
    }

    public String getContactId() {
        return contactId;
    }

    public void setContactId(String contactId) {
        this.contactId = contactId;
    }

    public int getAttempt() {
        return attempt;
    }

    public void setAttempt(int attempt) {
        this.attempt = attempt;
    }

    public double getAtSeconds() {
        return atSeconds;
    }

    public void setAtSeconds(double atSeconds) {
        this.atSeconds = atSeconds;
    }

    public DeliveryStatus getStatus() {
        return status;
    }

    public void setStatus(DeliveryStatus status) {
        this.status = status;
    }

    public String getDetail() {
        return detail;
    }

    public void setDetail(String detail) {
        this.detail = detail == null ? "" : detail;
    }

    public boolean isDelivered() {
        return DeliveryStatus.DELIVERED == status;
    }
}
