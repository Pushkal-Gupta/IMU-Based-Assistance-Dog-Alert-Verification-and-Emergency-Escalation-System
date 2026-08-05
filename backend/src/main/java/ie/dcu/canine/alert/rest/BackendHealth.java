package ie.dcu.canine.alert.rest;

import ie.dcu.canine.alert.domain.RelayHeartbeat;
import ie.dcu.canine.alert.service.AlertRepository;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;
import org.eclipse.microprofile.health.HealthCheck;
import org.eclipse.microprofile.health.HealthCheckResponse;
import org.eclipse.microprofile.health.Readiness;

import java.time.Duration;
import java.time.Instant;
import java.util.List;

/**
 * Readiness probe.
 *
 * <p>Reports the number of relays currently reporting alongside the usual UP.
 * A backend with zero live relays is technically healthy and operationally
 * useless -- the collars are unattached and no alert can arrive -- so it is
 * worth surfacing where a monitor can see it rather than only in the dashboard.
 */
@Readiness
@ApplicationScoped
public class BackendHealth implements HealthCheck {

    private static final Duration LIVE_WITHIN = Duration.ofMinutes(2);

    @Inject
    AlertRepository repository;

    @Override
    public HealthCheckResponse call() {
        Instant now = Instant.now();
        List<RelayHeartbeat> relays = repository.heartbeats();
        long live = relays.stream().filter(h -> !h.isStale(LIVE_WITHIN, now)).count();

        return HealthCheckResponse.named("alert-backend")
                .status(true)
                .withData("alerts_stored", repository.size())
                .withData("relays_known", relays.size())
                .withData("relays_live", live)
                .build();
    }
}
