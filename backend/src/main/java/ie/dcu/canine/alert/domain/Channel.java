package ie.dcu.canine.alert.domain;

/** Who a notification is addressed to. Mirrors {@code escalation.model.Channel}. */
public enum Channel {
    OWNER,
    CAREGIVER,
    EMERGENCY
}
