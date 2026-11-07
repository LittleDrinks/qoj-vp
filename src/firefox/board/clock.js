// Replay visibility and the team's scoring window are separate boundaries.
export function canReplay(session, elapsedMs = session.elapsedMs ?? 0) {
  return session.startAt != null && (session.finishedAt != null ||
    session.state === 'finished' || session.state === 'archived' || elapsedMs >= session.durationMs);
}

export function visibleElapsed(session, requestedMs = null) {
  if (session.startAt == null) return 0;
  const live = Math.max(0, Math.min(session.durationMs, session.elapsedMs ?? 0));
  const maximum = canReplay(session) ? session.durationMs : live;
  return Math.max(0, Math.min(maximum, requestedMs ?? live));
}
