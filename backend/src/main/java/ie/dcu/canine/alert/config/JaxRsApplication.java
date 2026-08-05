package ie.dcu.canine.alert.config;

import jakarta.ws.rs.ApplicationPath;
import jakarta.ws.rs.core.Application;

/** Roots the REST API at {@code /api/v1}, matching docs/06-api.md. */
@ApplicationPath("/api/v1")
public class JaxRsApplication extends Application {
}
