package ie.dcu.canine.alert.service;

import jakarta.annotation.Resource;
import jakarta.ejb.Schedule;
import jakarta.ejb.Singleton;
import jakarta.inject.Inject;

import java.time.Instant;
import java.util.logging.Logger;

/**
 * Drives {@link EscalationWatchdog} on a timer.
 *
 * <p>Kept separate from the watchdog itself so the escalation decision has no
 * scheduling dependency and can be unit-tested by calling {@code sweep(now)}
 * with an explicit instant. Timing logic that can only be exercised by waiting
 * is timing logic that does not get tested.
 *
 * <p>Every five seconds is far more often than needed -- the tolerances are
 * measured in minutes -- but a sweep over the open alerts is cheap, and being
 * late to escalate is the one cost this system should not pay.
 */
@Singleton
public class WatchdogScheduler {

    private static final Logger LOG = Logger.getLogger(WatchdogScheduler.class.getName());

    @Inject
    EscalationWatchdog watchdog;

    @Schedule(second = "*/5", minute = "*", hour = "*", persistent = false)
    public void run() {
        try {
            int escalated = watchdog.sweep(Instant.now()).size();
            if (escalated > 0) {
                LOG.warning(() -> "watchdog escalated " + escalated + " alert(s)");
            }
        } catch (RuntimeException error) {
            // An exception escaping a timer callback can silently stop the timer
            // in some containers, which would disable the watchdog for good.
            LOG.severe(() -> "watchdog sweep failed: " + error);
        }
    }
}
