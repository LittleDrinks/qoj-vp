import {
  calculateProblemStatistics,
  formatTimeDuration,
  getCCPC26ProblemLayout,
  getSortedCalculatedRawSolutions,
  resolveText,
  resolveUserMarkers,
} from '@algoux/standard-ranklist-utils';
import {
  DEFAULT_STYLED_RANKLIST_SETTINGS,
  normalizeStyledRanklistSettings,
} from '../../../vendor/rankland-web/src/client/components/ranklist/styled-ranklist-settings.ts';
import {canReplay} from './clock.js';
export {canReplay} from './clock.js';

export {
  LARGE_RANKLIST_THRESHOLD,
  RANKLIST_ROW_HEIGHT,
  initialRanklistRowWindow as initialRowWindow,
  getUniformRowWindow as uniformRowWindow,
} from '../../../vendor/rankland-web/src/client/components/ranklist/ranklist-row-window.ts';

export const LANGUAGES = ['zh-CN', 'en'];
export const OWN_TEAM_ID = '__qoj_vp_local_team__';
export const SPEEDS = [1, 2, 5, 10, 30, 60];

export const DEFAULT_SETTINGS = Object.freeze({
  ...DEFAULT_STYLED_RANKLIST_SETTINGS,
  theme: 'system',
  feed: true,
});

export function normalizeSettings(value) {
  return {
    ...normalizeStyledRanklistSettings(value),
    theme: ['system', 'light', 'dark'].includes(value?.theme) ? value.theme : 'system',
    feed: value?.feed !== false,
  };
}

export function normalizeFilter(value) {
  return {
    organizations: Array.isArray(value?.organizations) ? [...new Set(value.organizations.filter(item => typeof item === 'string'))].slice(0, 1000) : [],
    officialOnly: value?.officialOnly === true,
    marker: typeof value?.marker === 'string' ? value.marker : '',
  };
}

export function clampElapsed(value, durationMs) {
  return Math.max(0, Math.min(durationMs, Number.isFinite(value) ? value : 0));
}

export function liveElapsed(session, now = Date.now()) {
  if (session?.startAt === null || session?.startAt === undefined) return 0;
  const start = Number(session.startAt);
  const duration = Number(session.durationMs);
  if (!Number.isFinite(start) || !Number.isFinite(duration) || duration < 0) return 0;
  const finished = session.finishedAt === null || session.finishedAt === undefined ? now : Number(session.finishedAt);
  return clampElapsed(Math.min(now, finished) - start, duration);
}

export function initialPlayback(session, saved, now = Date.now()) {
  const duration = Number(session?.durationMs) || 0;
  const live = liveElapsed(session, now);
  const valid = saved && saved.version === 1 && saved.startAt === session?.startAt && Number.isFinite(saved.elapsedMs) &&
    Number.isFinite(saved.savedAt) && SPEEDS.includes(saved.speed) && typeof saved.playing === 'boolean' && saved.custom === true;
  if (!valid || !canReplay(session, live)) {
    return {custom: false, elapsedMs: live, playing: live < duration, speed: 1, anchorAt: now, anchorElapsedMs: live};
  }
  const elapsedMs = clampElapsed(saved.elapsedMs + (saved.playing ? Math.max(0, now - saved.savedAt) * saved.speed : 0), duration);
  return {custom: true, elapsedMs, playing: saved.playing && elapsedMs < duration, speed: saved.speed,
    anchorAt: now, anchorElapsedMs: elapsedMs};
}

export function advancePlayback(playback, liveMs, now, durationMs) {
  if (!playback.custom) return {elapsedMs: liveMs, playing: liveMs < durationMs};
  if (!playback.playing) return {elapsedMs: clampElapsed(playback.elapsedMs, durationMs), playing: false};
  const elapsedMs = clampElapsed(playback.anchorElapsedMs + Math.max(0, now - playback.anchorAt) * playback.speed, durationMs);
  return {elapsedMs, playing: elapsedMs < durationMs};
}

export function playbackForSeek(playback, elapsedMs, durationMs, now = Date.now()) {
  const elapsed = clampElapsed(elapsedMs, durationMs);
  return {...playback, custom: true, elapsedMs: elapsed, playing: false, anchorAt: now, anchorElapsedMs: elapsed};
}

export function playbackForToggle(playback, elapsedMs, liveMs, now, durationMs) {
  if (!playback.custom && liveMs < durationMs) {
    return {...playback, custom: true, elapsedMs: liveMs, playing: false, anchorAt: now, anchorElapsedMs: liveMs};
  }
  if (!playback.custom && liveMs >= durationMs) {
    return {custom: true, elapsedMs: 0, playing: true, speed: playback.speed, anchorAt: now, anchorElapsedMs: 0};
  }
  if (playback.playing) return {...playback, elapsedMs, playing: false, anchorAt: now, anchorElapsedMs: elapsedMs};
  const start = elapsedMs >= durationMs ? 0 : elapsedMs;
  return {...playback, custom: true, elapsedMs: start, playing: true, anchorAt: now, anchorElapsedMs: start};
}

export function actualRule(data) {
  return data?.sorter?.config?.extendedAlgorithms?.some(item => item.algorithm === 'CCPC26') ? 'CCPC26' : 'ICPC';
}

export function presentRanklist(source, filter, settings) {
  const ccpc26Layout = settings.preferCCPC26 ? getCCPC26ProblemLayout(source) : undefined;
  const seriesIndexes = source.series.map((_, index) => index).filter(index => {
    const rule = source.series[index].rule;
    return !filter.marker || rule?.preset !== 'ICPC' || !rule.options?.filter?.byMarker || rule.options.filter.byMarker === filter.marker;
  });
  const rows = source.rows.filter(row => {
    if (filter.organizations.length && !filter.organizations.includes(resolveText(row.user.organization, LANGUAGES))) return false;
    if (filter.officialOnly && row.user.official === false) return false;
    if (filter.marker && !resolveUserMarkers(row.user, source.markers).some(marker => marker.id === filter.marker)) return false;
    return true;
  }).map(row => seriesIndexes.length === source.series.length ? row :
    {...row, rankValues: seriesIndexes.map(index => row.rankValues[index])});
  const statistics = calculateProblemStatistics({...source, rows});
  return {
    data: {...source, series: seriesIndexes.map(index => source.series[index]), rows,
      problems: source.problems.map((problem, index) => ({...problem, statistics: statistics[index] || problem.statistics}))},
    ccpc26Layout,
  };
}

export function timeline(data) {
  return getSortedCalculatedRawSolutions(data.rows);
}

function solutionKey(solution) {
  return JSON.stringify([solution[0], solution[1], solution[2], formatTimeDuration(solution[3], 'ms')]);
}

export function feedSolutions(previous, next, forward = true) {
  if (!forward) return [];
  const oldCounts = new Map();
  for (const solution of previous) oldCounts.set(solutionKey(solution), (oldCounts.get(solutionKey(solution)) || 0) + 1);
  const added = [];
  for (const solution of next) {
    const key = solutionKey(solution), count = oldCounts.get(key) || 0;
    if (count) oldCounts.set(key, count - 1); else added.push(solution);
  }
  return added.slice(-40);
}

export function formatClock(value) {
  const seconds = Math.max(0, Math.floor(value / 1000));
  return [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60].map(part => String(part).padStart(2, '0')).join(':');
}

export function formatContestTimeRange(startAt, duration) {
  const start = new Date(startAt).getTime();
  if (!Number.isFinite(start)) return {startText: '—', endText: '—'};
  const match = String(startAt).match(/([+-])([01]\d|2[0-3]):?([0-5]\d)$/);
  const offset = match ? (Number(match[2]) * 60 + Number(match[3])) * (match[1] === '-' ? -1 : 1) : -new Date(start).getTimezoneOffset();
  const format = stamp => {
    const date = new Date(stamp + offset * 60000), pad = value => String(value).padStart(2, '0');
    return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())} ${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}:${pad(date.getUTCSeconds())}`;
  };
  const suffix = `${offset >= 0 ? '+' : '-'}${String(Math.floor(Math.abs(offset) / 60)).padStart(2, '0')}:${String(Math.abs(offset) % 60).padStart(2, '0')}`;
  return {startText: format(start), endText: format(start + formatTimeDuration(duration, 'ms')) + ' ' + suffix};
}
