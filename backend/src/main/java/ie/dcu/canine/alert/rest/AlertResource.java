package ie.dcu.canine.alert.rest;

import ie.dcu.canine.alert.domain.AlertRecord;
import ie.dcu.canine.alert.domain.AlertState;
import ie.dcu.canine.alert.domain.RelayHeartbeat;
import ie.dcu.canine.alert.service.AlertRepository;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;
import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.PathParam;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.QueryParam;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * The alert API. Contract documented in {@code docs/06-api.md} and implemented
 * identically by {@code tools/devserver.py} for development.
 *
 * <p>Note what is <em>not</em> here: there is no endpoint to acknowledge or
 * escalate an alert. The ladder runs on the relay, and the backend records what
 * happened rather than deciding it. Adding a "resolve this alert" endpoint here
 * would create a second authority over the same state machine and a race
 * between them.
 */
@Path("/")
@ApplicationScoped
@Produces(MediaType.APPLICATION_JSON)
@Consumes(MediaType.APPLICATION_JSON)
public class AlertResource {

    @Inject
    AlertRepository repository;

    /**
     * Upsert an alert. Called by the relay on every state transition.
     *
     * <p>Returns 202 rather than 201: the relay has already acted on this alert,
     * and the backend is recording a fact rather than creating a resource on
     * request. A relay must never treat a non-2xx here as a reason to change
     * what it does -- it queues and retries.
     */
    @POST
    @Path("/alerts")
    public Response upsertAlert(AlertRecord alert) {
        if (alert == null || alert.getAlertId() == null || alert.getAlertId().isBlank()) {
            return badRequest("alert_id is required");
        }
        if (alert.getState() == null) {
            return badRequest("state is required");
        }
        if (alert.getLocation() != null && !alert.getLocation().isValid()) {
            return badRequest("location coordinates are out of range");
        }
        return Response.accepted(repository.upsert(alert)).build();
    }

    @GET
    @Path("/alerts")
    public Response listAlerts(@QueryParam("state") String state, @QueryParam("dog_id") String dogId) {
        AlertState filter = null;
        if (state != null && !state.isBlank()) {
            try {
                filter = AlertState.valueOf(state);
            } catch (IllegalArgumentException error) {
                return badRequest("unknown state: " + state);
            }
        }
        return Response.ok(Map.of("alerts", repository.findAll(filter, dogId))).build();
    }

    @GET
    @Path("/alerts/{alertId}")
    public Response getAlert(@PathParam("alertId") String alertId) {
        return repository.find(alertId)
                .map(alert -> Response.ok(alert).build())
                .orElseGet(() -> Response.status(Response.Status.NOT_FOUND)
                        .entity(Map.of("error", "no such alert: " + alertId))
                        .build());
    }

    @POST
    @Path("/heartbeats")
    public Response heartbeat(RelayHeartbeat heartbeat) {
        if (heartbeat == null || heartbeat.getRelayId() == null || heartbeat.getRelayId().isBlank()) {
            return badRequest("relay_id is required");
        }
        return Response.accepted(repository.recordHeartbeat(heartbeat)).build();
    }

    @GET
    @Path("/heartbeats")
    public Response heartbeats() {
        return Response.ok(Map.of("relays", repository.heartbeats())).build();
    }

    /**
     * Aggregate view for the caregiver dashboard.
     *
     * <p>This is the system's secondary contribution: over months these figures
     * say whether the dog's trained alert is still reliable and whether the
     * owner is still responding to it -- neither of which anyone can currently
     * measure.
     */
    @GET
    @Path("/summary")
    public Response summary() {
        List<AlertRecord> alerts = repository.findAll(null, null);

        Map<String, Integer> byState = new HashMap<>();
        int escalated = 0;
        int dismissed = 0;
        int open = 0;
        double responseTotal = 0.0;
        double responseMax = 0.0;
        int responded = 0;

        for (AlertRecord alert : alerts) {
            AlertState state = alert.getState();
            byState.merge(state == null ? "UNKNOWN" : state.name(), 1, Integer::sum);

            if (state == null || state.isOpen()) {
                open++;
            } else if (state == AlertState.ESCALATED_EMERGENCY
                    || state == AlertState.ACKNOWLEDGED_BY_CAREGIVER) {
                escalated++;
            } else if (state == AlertState.DISMISSED_FALSE_POSITIVE) {
                dismissed++;
            }

            Double response = alert.getOwnerResponseSeconds();
            if (response != null) {
                responded++;
                responseTotal += response;
                responseMax = Math.max(responseMax, response);
            }
        }

        int total = alerts.size();
        Map<String, Object> ownerResponse = new HashMap<>();
        ownerResponse.put("n", responded);
        ownerResponse.put("mean_seconds", responded > 0 ? responseTotal / responded : null);
        ownerResponse.put("max_seconds", responded > 0 ? responseMax : null);

        Map<String, Object> body = new HashMap<>();
        body.put("total_alerts", total);
        body.put("open_alerts", open);
        body.put("by_state", byState);
        body.put("escalated", escalated);
        body.put("escalation_rate", total > 0 ? (double) escalated / total : 0.0);
        body.put("dismissed_false_positive", dismissed);
        body.put("false_positive_rate", total > 0 ? (double) dismissed / total : 0.0);
        body.put("owner_response", ownerResponse);
        body.put("relays", repository.heartbeats());

        return Response.ok(body).build();
    }

    private static Response badRequest(String message) {
        return Response.status(Response.Status.BAD_REQUEST)
                .entity(Map.of("error", message, "status", 400))
                .build();
    }
}
