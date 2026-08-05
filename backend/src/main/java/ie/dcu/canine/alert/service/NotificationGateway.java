package ie.dcu.canine.alert.service;

import ie.dcu.canine.alert.domain.AlertRecord;
import ie.dcu.canine.alert.domain.Channel;
import ie.dcu.canine.alert.domain.DeliveryStatus;
import ie.dcu.canine.alert.domain.NotificationAttempt;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;
import org.eclipse.microprofile.config.inject.ConfigProperty;

import java.util.logging.Logger;

/**
 * Outbound notification from the backend.
 *
 * <p>Almost all paging is done by the relay, over SMS, without the backend
 * involved -- that is what keeps the safety path independent of the network.
 * This gateway exists for the one case the relay cannot cover: the watchdog
 * escalating because the relay itself has gone silent.
 *
 * <p>The default implementation logs. Wiring a real SMS provider means
 * replacing {@link #send} (or producing an alternative CDI bean); the escalation
 * logic does not change, which is the point of keeping the two apart.
 */
@ApplicationScoped
public class NotificationGateway {

    private static final Logger LOG = Logger.getLogger(NotificationGateway.class.getName());

    @Inject
    @ConfigProperty(name = "escalation.emergency.contact.id", defaultValue = "emerg-1")
    String emergencyContactId;

    @Inject
    @ConfigProperty(name = "escalation.owner.name", defaultValue = "the owner")
    String ownerName;

    /**
     * Page the emergency contact and record the attempt on the alert.
     *
     * <p>The attempt is recorded whether or not delivery succeeded: an incident
     * review needs to see that the backend tried and failed, which is invisible
     * if only successes are stored.
     */
    public void notifyEmergency(AlertRecord alert, String reason) {
        String message = compose(alert, reason);
        boolean delivered;
        String detail = "";
        try {
            delivered = send(emergencyContactId, message);
        } catch (RuntimeException error) {
            // A broken transport must not abort an escalation sweep that may
            // still have other alerts to handle.
            LOG.severe(() -> "emergency notification threw: " + error);
            delivered = false;
            detail = error.getClass().getSimpleName() + ": " + error.getMessage();
        }

        NotificationAttempt attempt = new NotificationAttempt();
        attempt.setChannel(Channel.EMERGENCY);
        attempt.setContactId(emergencyContactId);
        attempt.setAttempt(1);
        attempt.setAtSeconds(alert.getRaisedAtSeconds());
        attempt.setStatus(delivered ? DeliveryStatus.DELIVERED : DeliveryStatus.FAILED);
        attempt.setDetail(detail);
        alert.getNotifications().add(attempt);
    }

    String compose(AlertRecord alert, String reason) {
        StringBuilder text = new StringBuilder()
                .append("EMERGENCY: ").append(ownerName)
                .append("'s seizure-alert dog signalled an alert (confidence ")
                .append(Math.round(alert.getConfidence() * 100)).append("%). ")
                .append("The alert was not resolved and the owner's phone stopped reporting (")
                .append(reason).append("). Medical assistance may be required.");

        if (alert.getLocation() != null && alert.getLocation().isValid()) {
            text.append("\nLast known location: ")
                .append(String.format("%.5f, %.5f", alert.getLocation().getLatitude(),
                        alert.getLocation().getLongitude()))
                .append(String.format(" (+/-%.0f m, %.0f s old)",
                        alert.getLocation().getAccuracyM(), alert.getLocation().getAgeSeconds()));
        } else {
            text.append("\nNo recent location fix is available.");
        }
        return text.toString();
    }

    /**
     * Deliver a message. Replace with a real SMS or push transport.
     *
     * @return true when the message was accepted by the transport
     */
    protected boolean send(String contactId, String message) {
        LOG.severe(() -> "NOTIFY " + contactId + ": " + message);
        return true;
    }
}
