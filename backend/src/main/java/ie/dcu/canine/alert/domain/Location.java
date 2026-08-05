package ie.dcu.canine.alert.domain;

import jakarta.json.bind.annotation.JsonbProperty;

/**
 * A GPS fix attached to an alert.
 *
 * <p>{@code ageSeconds} is measured against the moment the alert was raised, not
 * against now, so a fix is judged by how stale it was <em>when it mattered</em>.
 * The relay drops fixes older than its configured limit before sending, because
 * a coordinate reads as authoritative and a stale one sends a responder to
 * where the owner used to be.
 */
public class Location {

    private double latitude;
    private double longitude;

    @JsonbProperty("accuracy_m")
    private double accuracyM;

    @JsonbProperty("age_seconds")
    private double ageSeconds;

    public Location() {
        // Required by JSON-B.
    }

    public double getLatitude() {
        return latitude;
    }

    public void setLatitude(double latitude) {
        this.latitude = latitude;
    }

    public double getLongitude() {
        return longitude;
    }

    public void setLongitude(double longitude) {
        this.longitude = longitude;
    }

    public double getAccuracyM() {
        return accuracyM;
    }

    public void setAccuracyM(double accuracyM) {
        this.accuracyM = accuracyM;
    }

    public double getAgeSeconds() {
        return ageSeconds;
    }

    public void setAgeSeconds(double ageSeconds) {
        this.ageSeconds = ageSeconds;
    }

    public boolean isValid() {
        return latitude >= -90.0 && latitude <= 90.0
                && longitude >= -180.0 && longitude <= 180.0
                && accuracyM >= 0.0 && ageSeconds >= 0.0;
    }
}
