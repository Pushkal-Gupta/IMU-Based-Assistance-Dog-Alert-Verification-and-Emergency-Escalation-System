import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';

const STATE = {
  PENDING_OWNER: ['Awaiting owner', 'blue'],
  PENDING_CAREGIVER: ['Awaiting caregiver', 'blue'],
  ACKNOWLEDGED_BY_OWNER: ['Owner responded', 'green'],
  ACKNOWLEDGED_BY_CAREGIVER: ['Caregiver responded', 'amber'],
  ESCALATED_EMERGENCY: ['Emergency escalation', 'red'],
  DISMISSED_FALSE_POSITIVE: ['Dismissed as false alarm', 'green'],
  CANCELLED: ['Cancelled', 'muted'],
};
const label = (s) => STATE[s]?.[0] || String(s || 'Unknown').replaceAll('_', ' ').toLowerCase();
const tone = (s) => STATE[s]?.[1] || 'muted';
const pct = (n) => n == null ? '—' : `${Math.round(Number(n) * 100)}%`;
const duration = (n) => n == null ? '—' : Number(n) < 90 ? `${Number(n).toFixed(1)} s` : `${(Number(n) / 60).toFixed(1)} min`;
const raised = (a) => a?.raised_at_seconds ? `${Number(a.raised_at_seconds).toFixed(1)} s uptime` : 'Time unavailable';
const activeFor = (a, role) => role === 'owner' ? a.state === 'PENDING_OWNER' : role === 'caregiver' ? a.state === 'PENDING_CAREGIVER' : a.state === 'ESCALATED_EMERGENCY';
const paths = { history: '/', owner: '/owner', caregiver: '/caregiver', emergency: '/emergency' };

function App() {
  const path = window.location.pathname.replace(/\/$/, '') || '/';
  const role = path === '/owner' ? 'owner' : path === '/caregiver' ? 'caregiver' : path === '/emergency' ? 'emergency' : 'history';
  const [alerts, setAlerts] = useState([]);
  const [summary, setSummary] = useState(null);
  const [relayOnline, setRelayOnline] = useState(false);
  const [backendOnline, setBackendOnline] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState({ text: '', kind: '' });
  const [expanded, setExpanded] = useState('');
  const [lastUpdated, setLastUpdated] = useState(null);

  const refresh = useCallback(async () => {
    let relayOk = false;
    try {
      const r = await fetch('/health', { cache: 'no-store' });
      relayOk = r.ok;
    } catch { relayOk = false; }
    setRelayOnline(relayOk);

    if (role === 'history') {
      try {
        const [s, a] = await Promise.all([
          fetch('/api/v1/summary', { cache: 'no-store' }),
          fetch('/api/v1/alerts', { cache: 'no-store' }),
        ]);
        if (!s.ok || !a.ok) throw new Error('The history backend is not responding.');
        const summaryData = await s.json();
        const alertData = await a.json();
        setSummary(summaryData);
        setAlerts(alertData.alerts || []);
        setBackendOnline(true);
        setError('');
        setLastUpdated(new Date());
      } catch (e) {
        setBackendOnline(false);
        setError(e.message || 'Could not load alert history.');
      }
      return;
    }

    if (!relayOk) {
      setError('Relay unavailable. Start gateway/relay.py and keep it running.');
      return;
    }
    try {
      const r = await fetch('/api/relay/alerts', { cache: 'no-store' });
      if (!r.ok) throw new Error('Could not load alerts from the relay.');
      const data = await r.json();
      setAlerts(data.alerts || []);
      setError('');
      setLastUpdated(new Date());
    } catch (e) { setError(e.message || 'Could not load alerts.'); }
  }, [role]);

  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, 2000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const current = useMemo(() => alerts.filter(a => activeFor(a, role)).sort((a, b) => (b.raised_at_seconds || 0) - (a.raised_at_seconds || 0))[0] || null, [alerts, role]);

  async function respond(action) {
    if (!current || busy) return;
    if (action === 'help') {
      setFeedback({ text: 'Please contact the caregiver or local emergency number directly. This demo button does not place an additional emergency call.', kind: 'warn' });
      return;
    }
    if (role === 'emergency') {
      setFeedback({ text: 'Receipt noted on this demo screen only. The incident remains escalated; no emergency service is contacted by this button.', kind: 'warn' });
      return;
    }
    setBusy(true);
    setFeedback({ text: 'Submitting your response…', kind: 'info' });
    try {
      const endpoint = action === 'dismiss' ? '/api/relay/dismiss' : '/api/relay/ack';
      const by = role === 'caregiver' ? 'CAREGIVER' : 'OWNER';
      const r = await fetch(endpoint, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ alert_id: current.alert_id, by }),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.error || `Request failed (${r.status})`);
      setFeedback({ text: 'Response submitted successfully.', kind: 'success' });
      await refresh();
    } catch (e) {
      setFeedback({ text: `Could not submit response: ${e.message}`, kind: 'error' });
    } finally { setBusy(false); }
  }

  const isHistory = role === 'history';
  const title = isHistory ? 'Assistance Dog Alert History' : role === 'owner' ? 'Owner response' : role === 'caregiver' ? 'Caregiver console' : 'Emergency contact';
  const subtitle = isHistory ? 'A clear audit trail of collar alerts, response times and escalation outcomes.' : role === 'owner' ? 'Confirm your status when the collar raises an alert.' : role === 'caregiver' ? 'Review and acknowledge an escalation when the owner has not responded.' : 'Review the final escalation stage and verify the situation.';

  return <div className={`app role-${role}`}>
    <div className="ambient ambient-one"/><div className="ambient ambient-two"/>
    <div className="layout">
      <header className="topbar">
        <a className="brand" href="/"><span className="brand-icon">✦</span><span><strong>PAWSAFE</strong><small>ASSISTANCE DOG SYSTEM</small></span></a>
        <nav className="nav" aria-label="Dashboard navigation">
          <NavLink href="/" active={isHistory} icon="▦">History</NavLink>
          <NavLink href="/owner" active={role === 'owner'} icon="◉">Owner</NavLink>
          <NavLink href="/caregiver" active={role === 'caregiver'} icon="♧">Caregiver</NavLink>
          <NavLink href="/emergency" active={role === 'emergency'} icon="＋">Emergency</NavLink>
        </nav>
        <div className={`connection ${isHistory ? (backendOnline ? 'online' : 'offline') : (relayOnline ? 'online' : 'offline')}`}><span className="pulse-dot"/>{isHistory ? (backendOnline ? 'Backend connected' : 'Backend offline') : (relayOnline ? 'Relay connected' : 'Relay offline')}</div>
      </header>

      <section className="page-heading">
        <div><div className="eyebrow"><span className="eyebrow-line"/>{isHistory ? 'SYSTEM OVERVIEW' : `${role.toUpperCase()} WORKSPACE`}</div><h1>{title}</h1><p>{subtitle}</p></div>
        <div className="heading-meta"><span className="live-indicator"><span/> LIVE MONITOR</span><span className="updated">{lastUpdated ? `Updated ${lastUpdated.toLocaleTimeString()}` : 'Connecting…'}</span></div>
      </section>

      {error && <div className="error-banner"><span>!</span><div><strong>Connection issue</strong><p>{error}</p></div><button className="button subtle" onClick={refresh}>Retry</button></div>}

      {isHistory ? <History summary={summary} alerts={alerts} expanded={expanded} setExpanded={setExpanded} refresh={refresh} backendOnline={backendOnline}/> : <RoleDashboard role={role} alerts={alerts} current={current} busy={busy} feedback={feedback} onRespond={respond} relayOnline={relayOnline}/>}

      <footer className="footer"><span>PAWSAFE · Local safety console</span><span>Prototype for demonstration · Not a validated emergency-response service</span></footer>
    </div>
  </div>;
}

function NavLink({ href, active, icon, children }) { return <a className={`nav-link ${active ? 'selected' : ''}`} href={href}><span>{icon}</span>{children}</a>; }

function History({ summary, alerts, expanded, setExpanded, refresh, backendOnline }) {
  const stats = summary ? [
    { label: 'Total alerts', value: summary.total_alerts ?? alerts.length, note: 'Recorded incidents', icon: '◉', color: 'blue' },
    { label: 'Open alerts', value: summary.open_alerts ?? '—', note: 'Awaiting resolution', icon: '◷', color: 'amber' },
    { label: 'Escalated', value: summary.escalated ?? '—', note: `${Math.round((summary.escalation_rate || 0) * 100)}% of alerts`, icon: '↗', color: 'red' },
    { label: 'Owner response', value: summary.owner_response?.mean_seconds == null ? '—' : duration(summary.owner_response.mean_seconds), note: `${summary.owner_response?.n || 0} responses recorded`, icon: '✓', color: 'green' },
    { label: 'Below threshold', value: summary.suppressed_detections ?? '—', note: 'Detections not paged', icon: '⌁', color: 'violet' },
  ] : [];
  return <>
    <section className="stats-grid">{stats.map(s => <article className="stat-card" key={s.label}><div className={`stat-icon ${s.color}`}>{s.icon}</div><div className="stat-label">{s.label}</div><div className="stat-value">{s.value}</div><div className="stat-note">{s.note}</div></article>)}</section>
    <section className="panel">
      <div className="panel-heading"><div><div className="eyebrow">AUDIT LOG</div><h2>Recent incidents</h2><p>Expand an incident to inspect its state transitions and notification attempts.</p></div><button className="button subtle" onClick={refresh}>↻ Refresh</button></div>
      <div className="table-wrap"><table><thead><tr><th>Raised</th><th>Collar</th><th>Outcome</th><th>Confidence</th><th>Owner response</th><th>Notifications</th></tr></thead><tbody>
        {alerts.map(a => <React.Fragment key={a.alert_id}><tr className="alert-row" onClick={() => setExpanded(expanded === a.alert_id ? '' : a.alert_id)} aria-expanded={expanded === a.alert_id}><td><span className="mono">{raised(a)}</span></td><td><strong>{a.dog_id || '—'}</strong></td><td><StatusBadge state={a.state}/></td><td>{pct(a.confidence)}</td><td>{duration(a.owner_response_seconds)}</td><td>{(a.notifications || []).length ? `${a.notifications.length} attempt(s)` : '—'} <span className="row-chevron">{expanded === a.alert_id ? '−' : '+'}</span></td></tr>
          {expanded === a.alert_id && <tr className="detail-row"><td colSpan="6"><div className="detail-grid"><div><span>Incident ID</span><code>{a.alert_id}</code></div><div><span>Current state</span><strong>{label(a.state)}</strong></div><div><span>Transitions</span><strong>{(a.transitions || []).length}</strong></div><div><span>Notification attempts</span><strong>{(a.notifications || []).length}</strong></div>{a.location && <div><span>Last location</span><strong>{Number(a.location.latitude).toFixed(5)}, {Number(a.location.longitude).toFixed(5)}</strong></div>}</div>
            {(a.transitions || []).length > 0 && <ol className="timeline">{a.transitions.map((t, i) => <li key={i}><span>{t.state || t.to_state || t.event || 'State update'}</span><small>{t.at_seconds != null ? `${Number(t.at_seconds).toFixed(1)} s` : ''}</small></li>)}</ol>}
          </td></tr>}</React.Fragment>)}
        {!alerts.length && <tr><td colSpan="6"><div className="empty-state"><span className="empty-mark">✓</span><strong>{backendOnline ? 'No incidents recorded yet' : 'Waiting for backend connection'}</strong><p>New collar events will appear here automatically.</p></div></td></tr>}
      </tbody></table></div>
      <div className="panel-foot"><span>{alerts.length} incident{alerts.length === 1 ? '' : 's'} in history</span><span>Auto-refresh every 2 seconds</span></div>
    </section>
  </>;
}

function StatusBadge({ state }) { return <span className={`status-badge ${tone(state)}`}><span className="status-dot"/>{label(state)}</span>; }

function RoleDashboard({ role, alerts, current, busy, feedback, onRespond, relayOnline }) {
  const roleInfo = {
    owner: { icon: '◉', color: 'green', heading: 'Your safety comes first', action: 'Confirm that you are okay', description: 'If you are safe, acknowledge the alert. If you need assistance, request help from your support network.' },
    caregiver: { icon: '♧', color: 'blue', heading: 'Caregiver escalation', action: 'Acknowledge this alert', description: 'Review the incident and confirm that you have received the escalation.' },
    emergency: { icon: '＋', color: 'red', heading: 'Emergency escalation', action: 'Review the escalated incident', description: 'The owner and caregiver did not resolve the alert within the configured response windows.' },
  }[role];
  const history = alerts.slice().sort((a,b) => (b.raised_at_seconds || 0) - (a.raised_at_seconds || 0)).slice(0, 6);
  return <div className="role-grid">
    <section className="panel main-alert-panel">
      <div className="panel-heading"><div><div className="eyebrow">CURRENT ALERT</div><h2>{role === 'owner' ? 'Owner response' : role === 'caregiver' ? 'Caregiver console' : 'Emergency contact'}</h2><p>{roleInfo.description}</p></div><span className={`role-chip ${roleInfo.color}`}>{role.toUpperCase()}</span></div>
      {current ? <>
        <div className={`current-alert ${roleInfo.color}`}><div className="alert-symbol">{roleInfo.icon}</div><div className="alert-body"><div className="alert-kicker">{label(current.state)}</div><h3>Possible assistance-dog alert detected</h3><p>A collar event needs your attention. Please verify the situation directly.</p><div className="alert-facts"><Fact label="Incident ID" value={current.alert_id || '—'} mono/><Fact label="Collar" value={current.dog_id || '—'}/><Fact label="Confidence" value={pct(current.confidence)}/></div></div></div>
        <div className="safety-note"><span>ⓘ</span><div><strong>Verify the situation directly.</strong><br/>This is a model-generated alert, not a confirmed medical emergency.</div></div>
        {role === 'emergency' && <div className="callout-warning">The emergency acknowledgement below records receipt on this demo screen only. It does not contact emergency services.</div>}
        <div className="response-area"><div><div className="eyebrow">RESPONSE ACTION</div><h3>{roleInfo.action}</h3></div><div className="action-buttons">
          {role === 'owner' && <><button className="button primary" disabled={busy} onClick={() => onRespond('ack')}>{busy ? 'Submitting…' : '✓  I’m OK'}</button><button className="button subtle" disabled={busy} onClick={() => onRespond('dismiss')}>↶  False alarm</button><button className="button danger" onClick={() => onRespond('help')}>!  Request help</button></>}
          {role === 'caregiver' && <button className="button primary" disabled={busy} onClick={() => onRespond('ack')}>{busy ? 'Submitting…' : '✓  Acknowledge alert'}</button>}
          {role === 'emergency' && <button className="button danger" onClick={() => onRespond('receipt')}>＋  Acknowledge receipt</button>}
        </div>{feedback.text && <div className={`feedback ${feedback.kind}`} role="status">{feedback.text}</div>}</div>
      </> : <div className="all-clear"><div className="all-clear-icon">✓</div><h3>{relayOnline ? 'You’re all clear' : 'Relay connection unavailable'}</h3><p>{relayOnline ? 'No active incident is waiting for you right now.' : 'Start gateway/relay.py and keep it running. This page will reconnect automatically.'}</p><div className="monitoring-pill"><span/> {relayOnline ? 'Monitoring for the next collar event' : 'Waiting for relay connection'}</div></div>}
    </section>
    <aside className="panel side-panel"><div className="panel-heading"><div><div className="eyebrow">ACTIVITY</div><h2>Recent incidents</h2><p>Latest events from the collar relay.</p></div></div><div className="mini-history">{history.map(a => <article className="mini-item" key={a.alert_id}><div className="mini-top"><span className="mini-id">{String(a.alert_id || 'incident').slice(0, 22)}</span><StatusBadge state={a.state}/></div><div className="mini-meta"><span>Collar <strong>{a.dog_id || '—'}</strong></span><span>{pct(a.confidence)}</span></div></article>)}{!history.length && <div className="empty-small">No incidents have been recorded yet.</div>}</div><div className="side-foot"><span className={`pulse-dot ${relayOnline ? '' : 'off'}`}/>{relayOnline ? 'Relay connected' : 'Relay disconnected'}<span className="side-foot-right">Auto-refresh · 2 sec</span></div></aside>
  </div>;
}
function Fact({ label, value, mono }) { return <div className="fact"><span>{label}</span><strong className={mono ? 'mono' : ''}>{value}</strong></div>; }

createRoot(document.getElementById('root')).render(<React.StrictMode><App/></React.StrictMode>);
