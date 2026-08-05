package ie.dcu.canine.alert.service;

import ie.dcu.canine.alert.domain.AlertRecord;
import ie.dcu.canine.alert.domain.AlertState;
import ie.dcu.canine.alert.domain.RelayHeartbeat;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;
import org.eclipse.microprofile.config.inject.ConfigProperty;

import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.logging.Logger;

/**
 * Escalates on a relay's behalf when the relay itself goes silent.
 *
 * <p>The escalation ladder runs on the owner's phone, because the alert matters
 * most exactly where connectivity is worst. That design has one hole: if the
 * phone dies while an alert is open, the ladder stops and nobody is ever paged.
 * The dog signalled, the owner did not respond, and the system quietly did
 * nothing -- which is the precise failure the project exists to prevent.
 *
 * <p>This watchdog closes it. While an alert is open the relay heartbeats every
 * few seconds; if those stop for longer than the tolerance <em>and</em> the
 * alert is still open, the backend escalates directly to the emergency contact.
 *
 * <p>It errs towards escalating. A spurious escalation caused by a dropped
 * network costs a caregiver a phone call; a missed one costs considerably more.
 * The alert is marked {@code escalatedByWatchdog} so the caregiver can see the
 * page came from the backend rather than from a confirmed non-response, and so
 * the rate of watchdog escalations can be monitored -- a high rate means the
 * relay's connectivity needs fixing, not that the owner is unresponsive.
 */
@ApplicationScoped
public class EscalationWatchdog {

    private static final Logger LOG = Logger.getLogger(EscalationWatchdog.class.getName());

    @Inject
    AlertRepository repository;

    @Inject
    NotificationGateway gateway;

    /**
     * How long a relay may go quiet before the backend takes over.
     *
     * <p>Must be comfortably longer than the relay's heartbeat interval times
     * the tolerated miss count, or ordinary jitter will trigger takeovers.
     * Default: 15 s heartbeat x 3 misses, plus margin.
     */
    @Inject
    @ConfigProperty(name = "escalation.watchdog.relay.timeout.seconds", defaultValue = "60")
    long relayTimeoutSeconds;

    /**
     * Absolute ceiling on how long any alert may stay open.
     *
     * <p>Covers the case where the relay is alive and heartbeating but has
     * somehow stalled: no alert may sit open forever regardless of the reason.
     */
    @Inject
    @ConfigProperty(name = "escalation.watchdog.alert.max.open.seconds", defaultValue = "600")
    long maxOpenSeconds;

    /**
     * Runs one sweep. Invoked on a schedule by {@code WatchdogScheduler}, and
     * called directly by the tests -- a watchdog whose only trigger is a timer
     * is a watchdog that cannot be tested.
     *
     * @return the alerts this sweep escalated
     */
    public List<AlertRecord> sweep(Instant now) {
        List<AlertRecord> escalated = new ArrayList<>();

        for (AlertRecord alert : repository.findOpen()) {
            String reason = takeoverReason(alert, now);
            if (reason == null) {
                continue;
            }

            LOG.warning(() -> "watchdog escalating " + alert.getAlertId() + ": " + reason);
            alert.setEscalatedByWatchdog(true);
            alert.recordTransition(AlertState.ESCALATED_EMERGENCY, reason, alert.getRaisedAtSeconds());
            gateway.notifyEmergency(alert, reason);
            repository.upsert(alert);
            escalated.add(alert);
        }
        return escalated;
    }

    /**
     * Why this alert should be taken over, or {@code null} to leave it alone.
     *
     * <p>Separated from {@link #sweep} so the decision can be tested without
     * any notification side effects.
     */
    String takeoverReason(AlertRecord alert, Instant now) {
        Duration openFor = Duration.between(alert.getReceivedAt(), now);
        if (openFor.getSeconds() > maxOpenSeconds) {
            return "alert stayed open for " + openFor.getSeconds()
                    + "s, beyond the " + maxOpenSeconds + "s ceiling";
        }

        Optional<RelayHeartbeat> heartbeat = repository.heartbeats().stream()
                .filter(h -> alert.getDogId() != null && alert.getDogId().equals(h.getDogId()))
                .findFirst();

        if (heartbeat.isEmpty()) {
            // No heartbeat has ever arrived for this dog. That means the relay
            // is not reporting at all -- but the alert reached us somehow, so
            // wait out the ceiling rather than escalating immediately on what
            // may just be a relay built without heartbeat support.
            return null;
        }

        Duration tolerance = Duration.ofSeconds(relayTimeoutSeconds);
        if (heartbeat.get().isStale(tolerance, now)) {
            long silent = Duration.between(heartbeat.get().getReceivedAt(), now).getSeconds();
            return "relay " + heartbeat.get().getRelayId() + " silent for " + silent
                    + "s while an alert was open";
        }
        return null;
    }
}
