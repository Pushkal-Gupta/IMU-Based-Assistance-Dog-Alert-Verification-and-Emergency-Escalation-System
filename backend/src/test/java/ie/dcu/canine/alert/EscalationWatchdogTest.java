package ie.dcu.canine.alert;

import ie.dcu.canine.alert.domain.AlertRecord;
import ie.dcu.canine.alert.domain.AlertState;
import ie.dcu.canine.alert.domain.Channel;
import ie.dcu.canine.alert.domain.DeliveryStatus;
import ie.dcu.canine.alert.domain.NotificationAttempt;
import ie.dcu.canine.alert.domain.RelayHeartbeat;
import ie.dcu.canine.alert.service.AlertRepository;
import ie.dcu.canine.alert.service.EscalationWatchdog;
import ie.dcu.canine.alert.service.NotificationGateway;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * The watchdog covers the one failure the relay cannot: the owner's phone dies
 * mid-alert, so the escalation ladder stops and nobody is ever paged.
 *
 * <p>Every test drives {@code sweep(now)} with an explicit instant rather than
 * waiting on a timer, which is why the watchdog takes {@code Instant} as a
 * parameter at all.
 */
class EscalationWatchdogTest {

    private AlertRepository repository;
    private RecordingGateway gateway;
    private EscalationWatchdog watchdog;
    private Instant now;

    /** Captures pages instead of sending them. */
    static class RecordingGateway extends NotificationGateway {
        final List<String> paged = new ArrayList<>();

        @Override
        public void notifyEmergency(AlertRecord alert, String reason) {
            paged.add(alert.getAlertId());
            NotificationAttempt attempt = new NotificationAttempt();
            attempt.setChannel(Channel.EMERGENCY);
            attempt.setContactId("emerg-1");
            attempt.setStatus(DeliveryStatus.DELIVERED);
            alert.getNotifications().add(attempt);
        }
    }

    @BeforeEach
    void setUp() {
        now = Instant.parse("2026-03-08T20:00:00Z");
        repository = new AlertRepository();
        gateway = new RecordingGateway();
        watchdog = new EscalationWatchdog();
        watchdog.repository = repository;
        watchdog.gateway = gateway;
        watchdog.relayTimeoutSeconds = 60;
        watchdog.maxOpenSeconds = 600;
    }

    private AlertRecord openAlert(String id) {
        AlertRecord alert = new AlertRecord();
        alert.setAlertId(id);
        alert.setDogId("stuart");
        alert.setState(AlertState.PENDING_OWNER);
        alert.setConfidence(0.8);
        alert.setRaisedAtSeconds(1000.0);
        return repository.upsert(alert);
    }

    private void heartbeat(Instant at) {
        RelayHeartbeat beat = new RelayHeartbeat();
        beat.setRelayId("relay-1");
        beat.setDogId("stuart");
        beat.setOpenAlerts(1);
        repository.recordHeartbeat(beat);
        beat.setReceivedAt(at);
    }

    @Test
    @DisplayName("a live relay keeps ownership of its own alert")
    void liveRelayIsLeftAlone() {
        openAlert("a1");
        heartbeat(now.minusSeconds(5));

        assertThat(watchdog.sweep(now)).isEmpty();
        assertThat(gateway.paged).isEmpty();
    }

    @Test
    @DisplayName("a silent relay with an open alert is taken over")
    void silentRelayIsTakenOver() {
        AlertRecord alert = openAlert("a1");
        heartbeat(now.minusSeconds(120));

        assertThat(watchdog.sweep(now)).containsExactly(alert);
        assertThat(alert.getState()).isEqualTo(AlertState.ESCALATED_EMERGENCY);
        assertThat(alert.isEscalatedByWatchdog()).isTrue();
        assertThat(gateway.paged).containsExactly("a1");
    }

    @Test
    @DisplayName("takeover is recorded with a reason a caregiver can read")
    void takeoverExplainsItself() {
        AlertRecord alert = openAlert("a1");
        heartbeat(now.minusSeconds(120));
        watchdog.sweep(now);

        assertThat(alert.getTransitions()).isNotEmpty();
        assertThat(alert.getTransitions().get(alert.getTransitions().size() - 1).getReason())
                .contains("silent for")
                .contains("relay-1");
    }

    @Test
    @DisplayName("a closed alert is never escalated, however silent the relay")
    void closedAlertsAreIgnored() {
        AlertRecord alert = openAlert("a1");
        alert.setState(AlertState.ACKNOWLEDGED_BY_OWNER);
        repository.upsert(alert);
        heartbeat(now.minusSeconds(3600));

        assertThat(watchdog.sweep(now)).isEmpty();
        assertThat(gateway.paged).isEmpty();
    }

    @Test
    @DisplayName("one takeover per alert, not one per sweep")
    void takeoverHappensOnce() {
        openAlert("a1");
        heartbeat(now.minusSeconds(120));

        watchdog.sweep(now);
        watchdog.sweep(now.plusSeconds(5));
        watchdog.sweep(now.plusSeconds(10));

        assertThat(gateway.paged).containsExactly("a1");
    }

    @Test
    @DisplayName("an alert open past the ceiling escalates even with a live relay")
    void stalledRelayStillEscalates() {
        AlertRecord alert = openAlert("a1");
        alert.setReceivedAt(now.minusSeconds(900));
        heartbeat(now.minusSeconds(1));

        assertThat(watchdog.sweep(now)).containsExactly(alert);
        assertThat(alert.getTransitions().get(0).getReason()).contains("beyond the");
    }

    @Test
    @DisplayName("a relay that has never heartbeated is given until the ceiling")
    void unknownRelayWaitsForTheCeiling() {
        AlertRecord alert = openAlert("a1");
        // No heartbeat at all: the relay may simply not implement them, so do
        // not escalate on that alone.
        assertThat(watchdog.sweep(now)).isEmpty();

        alert.setReceivedAt(now.minusSeconds(900));
        assertThat(watchdog.sweep(now)).containsExactly(alert);
    }

    @Test
    @DisplayName("the tolerance boundary is honoured")
    void toleranceBoundary() {
        openAlert("a1");
        heartbeat(now.minusSeconds(60));
        assertThat(watchdog.sweep(now)).isEmpty();

        heartbeat(now.minusSeconds(61));
        assertThat(watchdog.sweep(now)).hasSize(1);
    }

    @Test
    @DisplayName("only the affected dog's alerts are taken over")
    void otherDogsAreUnaffected() {
        AlertRecord mine = openAlert("a1");
        AlertRecord theirs = new AlertRecord();
        theirs.setAlertId("b1");
        theirs.setDogId("rosie");
        theirs.setState(AlertState.PENDING_OWNER);
        repository.upsert(theirs);

        heartbeat(now.minusSeconds(120));

        List<AlertRecord> escalated = watchdog.sweep(now);
        assertThat(escalated).contains(mine);
        assertThat(theirs.getState()).isEqualTo(AlertState.PENDING_OWNER);
    }
}
