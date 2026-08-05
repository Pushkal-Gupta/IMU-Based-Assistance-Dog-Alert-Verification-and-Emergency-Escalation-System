package ie.dcu.canine.alert.service;

import ie.dcu.canine.alert.domain.AlertRecord;
import ie.dcu.canine.alert.domain.AlertState;
import ie.dcu.canine.alert.domain.RelayHeartbeat;
import jakarta.annotation.PostConstruct;
import jakarta.enterprise.context.ApplicationScoped;

import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;
import java.util.logging.Logger;

/**
 * Storage for alerts and relay heartbeats.
 *
 * <p>Backed by concurrent maps rather than JPA. That is a deliberate scope
 * choice for this stage of the project, not an oversight: the volume is a
 * handful of alerts per dog per week, the dashboard reads the whole set, and
 * keeping persistence out of the way made it possible to pin the escalation
 * semantics down in tests first. {@code docs/09-limitations.md} records this as
 * the first thing to change before any real deployment -- an audit log for a
 * safety system must outlive a container restart.
 *
 * <p>The append-only JSONL store in {@code tools/devserver.py} is the shape the
 * durable version should take: a state change is a new row, never a rewrite, so
 * the log can answer "what did the system do, and when did it know it".
 */
@ApplicationScoped
public class AlertRepository {

    private static final Logger LOG = Logger.getLogger(AlertRepository.class.getName());

    private final Map<String, AlertRecord> alerts = new ConcurrentHashMap<>();
    private final Map<String, RelayHeartbeat> heartbeats = new ConcurrentHashMap<>();

    @PostConstruct
    void warn() {
        LOG.warning("AlertRepository is in-memory; alert history will not survive a restart");
    }

    /**
     * Insert or update an alert, keyed on its id.
     *
     * <p>Idempotent by design. The relay derives an alert's id from the episode
     * rather than from arrival time, so a BLE retransmission or a queue flush
     * after an outage replays into the same row instead of creating a duplicate
     * that would page a caregiver twice.
     */
    public AlertRecord upsert(AlertRecord record) {
        record.setReceivedAt(Instant.now());
        alerts.put(record.getAlertId(), record);
        return record;
    }

    public Optional<AlertRecord> find(String alertId) {
        return Optional.ofNullable(alerts.get(alertId));
    }

    /** Newest first, which is the order the dashboard reads. */
    public List<AlertRecord> findAll(AlertState state, String dogId) {
        List<AlertRecord> found = new ArrayList<>(alerts.values());
        found.removeIf(a -> state != null && a.getState() != state);
        found.removeIf(a -> dogId != null && !dogId.equals(a.getDogId()));
        found.sort(Comparator.comparingDouble(AlertRecord::getRaisedAtSeconds).reversed());
        return found;
    }

    public List<AlertRecord> findOpen() {
        List<AlertRecord> open = new ArrayList<>();
        for (AlertRecord record : alerts.values()) {
            if (record.getState() != null && record.getState().isOpen()) {
                open.add(record);
            }
        }
        return open;
    }

    public RelayHeartbeat recordHeartbeat(RelayHeartbeat heartbeat) {
        heartbeat.setReceivedAt(Instant.now());
        heartbeats.put(heartbeat.getRelayId(), heartbeat);
        return heartbeat;
    }

    public List<RelayHeartbeat> heartbeats() {
        return new ArrayList<>(heartbeats.values());
    }

    public Optional<RelayHeartbeat> heartbeat(String relayId) {
        return Optional.ofNullable(heartbeats.get(relayId));
    }

    public int size() {
        return alerts.size();
    }
}
