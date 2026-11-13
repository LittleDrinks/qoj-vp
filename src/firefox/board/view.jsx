import React from 'react';
import {createRoot} from 'react-dom/client';
import {
  DefaultSolutionModal,
  DefaultUserModal,
  Modal,
} from '../../../vendor/standard-ranklist-renderer-component/packages/react/src/main.ts';
import {
  EnumTheme,
  formatTimeDuration,
  resolveContributor,
  resolveText,
} from '@algoux/standard-ranklist-utils';
import {ProblemDetails} from './details.jsx';
import {VirtualRanklist} from './virtual-ranklist.jsx';
import {
  LANGUAGES,
  OWN_TEAM_ID,
  SPEEDS,
  actualRule,
  advancePlayback,
  canReplay,
  feedSolutions,
  formatClock,
  formatContestTimeRange,
  initialPlayback,
  liveElapsed,
  normalizeFilter,
  normalizeSettings,
  playbackForSeek,
  playbackForToggle,
  presentRanklist,
  timeline,
} from './view-model.js';

const roots = new WeakMap();
const SETTINGS_KEY = 'qojVpBoardDisplayV2';
const FILTER_PREFIX = 'qojVpBoardFilterV1:';
const PLAYBACK_PREFIX = 'qojVpBoardPlaybackV1:';
const text = value => resolveText(value, LANGUAGES);

function readJson(key) {
  try { return JSON.parse(localStorage.getItem(key)); } catch (_) { return null; }
}
function writeJson(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch (_) { /* Display preferences are optional. */ }
}
function removeLocal(key) {
  try { localStorage.removeItem(key); } catch (_) { /* Display preferences are optional. */ }
}

function Icon({name}) {
  const paths = {
    download: <><path d="M12 3v12m0 0 4-4m-4 4-4-4"/><path d="M4 15v5h16v-5"/></>,
    share: <><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="m8.6 10.5 6.8-4M8.6 13.5l6.8 4"/></>,
    settings: <><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1a1.7 1.7 0 0 0 1.9.3A1.7 1.7 0 0 0 10 3v-.2h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1Z"/></>,
    external: <><path d="M14 4h6v6M20 4l-9 9"/><path d="M18 13v6H5V6h6"/></>,
    chevron: <path d="m6 9 6 6 6-6"/>,
    close: <path d="M6 6l12 12M18 6 6 18"/>,
    sun: <><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4m0-14.2-1.4 1.4M6.3 17.7l-1.4 1.4"/></>,
    moon: <path d="M20.5 14.2A8.5 8.5 0 0 1 9.8 3.5 8.5 8.5 0 1 0 20.5 14.2Z"/>,
    monitor: <><rect x="3" y="4" width="18" height="13" rx="1"/><path d="M8 21h8m-4-4v4"/></>,
  };
  return <svg className="qoj-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

function Switch({checked, onChange, label}) {
  return <button type="button" className="srk-ranklist-switch qoj-switch" role="switch" aria-label={label} aria-checked={checked}
    data-state={checked ? 'checked' : 'unchecked'} onClick={() => onChange(!checked)}><span /></button>;
}

function ToggleGroup({value, values, onChange, dataId}) {
  return <div className="srk-ranklist-marker-filter" data-id={dataId}>
    {values.map(([key, label]) => <button type="button" key={key} className="srk-ranklist-marker-filter-item srk-ranklist-setting-toggle-item"
      data-state={value === key ? 'on' : 'off'} aria-pressed={value === key} onClick={() => onChange(key)}>{label}</button>)}
  </div>;
}

function OrganizationFilter({organizations, selected, onChange}) {
  const [open, setOpen] = React.useState(false), [query, setQuery] = React.useState('');
  const root = React.useRef(null), search = React.useRef(null);
  const matching = organizations.filter(item => item.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  React.useEffect(() => {
    if (!open) return;
    search.current?.focus();
    const pointer = event => {if (!root.current?.contains(event.target)) setOpen(false);};
    const key = event => {if (event.key === 'Escape') {event.stopPropagation(); setOpen(false);}};
    document.addEventListener('pointerdown', pointer); document.addEventListener('keydown', key);
    return () => {document.removeEventListener('pointerdown', pointer); document.removeEventListener('keydown', key);};
  }, [open]);
  const toggle = organization => onChange(selected.includes(organization) ? selected.filter(item => item !== organization) : [...selected, organization]);
  return <span className={`srk-multi-select ${open ? 'is-open' : ''}`} ref={root}>
    <span className="srk-ranklist-org-select srk-multi-select-trigger" data-id="ranklist-org-multi-select" tabIndex="0" role="combobox"
      aria-haspopup="listbox" aria-expanded={open} aria-label="组织/单位筛选"
      onClick={() => setOpen(value => !value)} onKeyDown={event => {if (['Enter', ' '].includes(event.key)) {event.preventDefault(); setOpen(value => !value);}}}>
      <span className="srk-multi-select-open-button"><span className={`srk-multi-select-trigger-text ${selected.length ? '' : 'is-placeholder'}`}
        data-id={selected.length ? 'ranklist-org-selected-count' : undefined}>{selected.length ? `已选择 ${selected.length} 个` : '选择组织/单位'}</span></span>
      {selected.length > 0 && <button type="button" className="srk-multi-select-clear" data-id="ranklist-org-clear" aria-label="清空组织筛选"
        onClick={event => {event.stopPropagation(); onChange([]); setOpen(false);}}><Icon name="close" /></button>}
      <span className="srk-multi-select-chevron-button" aria-hidden="true"><span className="srk-multi-select-chevron"><Icon name="chevron" /></span></span>
    </span>
    {open && <div className="srk-multi-select-dropdown">
      <input ref={search} className="srk-multi-select-search" data-id="ranklist-org-search" type="search" placeholder="搜索组织/单位"
        aria-label="搜索组织/单位" value={query} onChange={event => setQuery(event.target.value)} />
      <div className="srk-multi-select-options" role="listbox" aria-multiselectable="true">
        {matching.map(organization => <button type="button" className="srk-multi-select-option" role="option" aria-selected={selected.includes(organization)}
          data-id={`ranklist-org-option-${organization}`} key={organization} onClick={() => toggle(organization)}>
          <span className="srk-multi-select-option-check">{selected.includes(organization) ? '✓' : ''}</span>
          <span className="srk-multi-select-option-label">{organization}</span>
        </button>)}
        {!matching.length && <span className="srk-multi-select-empty">无匹配项</span>}
      </div>
    </div>}
  </span>;
}

function ViewProgress({session, playback, elapsedMs, liveMs, frozenDuration, onSeek}) {
  const durationMs = Number(session.durationMs), prepared = session.startAt === null || session.startAt === undefined;
  const replay = canReplay(session, liveMs);
  const [draft, setDraft] = React.useState(null);
  const percent = durationMs ? elapsedMs / durationMs * 100 : 0;
  const frozenMs = frozenDuration ? formatTimeDuration(frozenDuration, 'ms') : 0;
  const freezeAt = durationMs ? 1 - frozenMs / durationMs : 1;
  const normalPercent = freezeAt ? Math.min(100, percent / freezeAt) : 0;
  const frozenPercent = freezeAt < 1 ? Math.min(100, Math.max(0, (percent / 100 - freezeAt) / (1 - freezeAt))) : 0;
  const center = prepared ? '准备中' : playback.custom ? '回放模式' : replay ? '已结束' : 'Live';
  const commit = () => {if (draft !== null) {if (replay) onSeek(draft * 60000); setDraft(null);}};
  const sliderValue = draft ?? Math.floor(elapsedMs / 60000);
  return <div className="srk-progress-bar-container" data-playback={playback.custom ? 'custom' : 'live'}>
    <div className="srk-progress-bar">
      <div className="srk-progress-bar-body">
        <div className="srk-progress-bar-segment srk-progress-bar-normal" style={{width: `${freezeAt * 100}%`}}><div className="srk-progress-bar-fill" style={{width: `${normalPercent}%`}} /></div>
        <div className="srk-progress-bar-segment srk-progress-bar-frozen" style={{width: `${(1 - freezeAt) * 100}%`}}><div className="srk-progress-bar-fill" style={{width: `${frozenPercent}%`}} /></div>
      </div>
      <div className="srk-progress-slider-layer"><input aria-label="Time Travel" className="srk-progress-slider" type="range" min="0"
        max={Math.ceil(durationMs / 60000)} step="1" disabled={!replay} value={sliderValue} title={replay ? formatClock(sliderValue * 60000) : '赛后可回放'}
        onChange={event => setDraft(Number(event.target.value))} onPointerUp={commit} onKeyUp={commit} onBlur={commit} /></div>
    </div>
    <div className="srk-progress-secondary-area">
      <div className="srk-progress-secondary-area-left">Elapsed: {formatClock(elapsedMs)}</div>
      <div className={`srk-progress-secondary-area-center ${!replay && !prepared ? 'srk-progress-live-text' : 'srk-progress-time-machine-status'}`}>{center}</div>
      <div className="srk-progress-secondary-area-right">Remaining: {formatClock(durationMs - elapsedMs)}</div>
    </div>
  </div>;
}

function SettingRow({label, children, tip}) {
  return <div className="srk-ranklist-setting-item"><span className="srk-ranklist-setting-label" title={tip}>{label}</span><span className="srk-ranklist-setting-control">{children}</span></div>;
}

function SettingsModal({open, settings, rule, theme, onChange, onClose}) {
  const rootClassName = `srk-general-modal-root qoj-theme-${theme}`;
  return <Modal open={open} title="榜单偏好设置" width={520} rootClassName={rootClassName} onClose={onClose}>
    <div className="srk-ranklist-settings-modal">
      <section className="srk-ranklist-settings-section"><h3>功能设置</h3>
        <SettingRow label="Pro 模式" tip="显示统计底栏和额外 Dirt/SE 列"><Switch checked={settings.professionalMode} label="Pro 模式" onChange={value => onChange('professionalMode', value)} /></SettingRow>
        {rule === 'CCPC26' && <SettingRow label="CCPC26 动态揭题"><Switch checked={settings.preferCCPC26} label="CCPC26 动态揭题" onChange={value => onChange('preferCCPC26', value)} /></SettingRow>}
      </section>
      <section className="srk-ranklist-settings-section"><h3>视觉设置</h3>
        <SettingRow label="明暗主题"><ToggleGroup value={settings.theme} dataId="ranklist-setting-theme" values={[['system', '跟随系统'], ['light', '浅色'], ['dark', '深色']]} onChange={value => onChange('theme', value)} /></SettingRow>
        <SettingRow label="提交状态风格预设"><ToggleGroup value={settings.statusCellPreset} dataId="ranklist-setting-status-cell-preset"
          values={[['classic', '经典'], ['detailed', '详细'], ['minimal', '极简'], ['compact', '紧凑']]} onChange={value => onChange('statusCellPreset', value)} /></SettingRow>
        <SettingRow label="提交高亮模式"><ToggleGroup value={settings.statusColorAsText ? 'text' : 'background'} dataId="ranklist-setting-status-highlight"
          values={[['background', '背景'], ['text', '文字']]} onChange={value => onChange('statusColorAsText', value === 'text')} /></SettingRow>
        <SettingRow label="空提交占位符"><ToggleGroup value={settings.emptyStatusPlaceholder} dataId="ranklist-setting-empty-placeholder"
          values={[['none', '无'], ['dot', 'Dot'], ['dash', 'Dash']]} onChange={value => onChange('emptyStatusPlaceholder', value)} /></SettingRow>
        <SettingRow label="表格斑马纹"><Switch checked={settings.rowStriped} label="表格斑马纹" onChange={value => onChange('rowStriped', value)} /></SettingRow>
        <SettingRow label="表格边框"><Switch checked={settings.tableBordered} label="表格边框" onChange={value => onChange('tableBordered', value)} /></SettingRow>
        <SettingRow label="分离 Organization 列"><Switch checked={settings.splitOrganization} label="分离 Organization 列" onChange={value => onChange('splitOrganization', value)} /></SettingRow>
        {settings.splitOrganization && <SettingRow label="徽标/头像位置"><ToggleGroup value={settings.userAvatarPlacement} dataId="ranklist-setting-avatar-placement"
          values={[['organization', 'Organization'], ['user', 'Name']]} onChange={value => onChange('userAvatarPlacement', value)} /></SettingRow>}
      </section>
    </div>
  </Modal>;
}

const FEED_LIFETIME = {FB: 180000, AC: 20000, '?': 10000};
function SubmissionFeed({events, enabled}) {
  const [cards, setCards] = React.useState([]);
  const queue = React.useRef([]), timer = React.useRef(null), nextId = React.useRef(1);
  const removeTimers = React.useRef([]);
  const show = React.useCallback(event => {
    const id = nextId.current++, lifetime = FEED_LIFETIME[event.result] || 10000;
    setCards(current => [...current, {id, event}].slice(-Math.max(1, Math.floor(window.innerHeight / 45))));
    const handle = window.setTimeout(() => setCards(current => current.filter(card => card.id !== id)), lifetime);
    removeTimers.current.push(handle);
  }, []);
  const pump = React.useCallback(() => {
    timer.current = null;
    if (!queue.current.length) return;
    const maximum = Math.max(1, Math.floor(window.innerHeight / 45));
    const ratio = queue.current.length <= maximum ? 1 : Math.max(1 / (queue.current.length / maximum) - 0.5, 0.01);
    show(queue.current.shift());
    timer.current = window.setTimeout(pump, Math.max(10, 100 * ratio));
  }, [show]);
  React.useEffect(() => {
    if (!enabled) return;
    for (const event of events) {
      if (event.result === 'FB') show(event); else queue.current.push(event);
    }
    if (queue.current.length && timer.current === null) pump();
  }, [events, enabled, pump, show]);
  React.useEffect(() => {
    if (enabled) return;
    queue.current = []; setCards([]);
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = null;
    for (const handle of removeTimers.current) window.clearTimeout(handle);
    removeTimers.current = [];
  }, [enabled]);
  React.useEffect(() => () => {
    if (timer.current !== null) window.clearTimeout(timer.current);
    for (const handle of removeTimers.current) window.clearTimeout(handle);
  }, []);
  if (!enabled) return null;
  return <div className="plugin_scroll-solution-container" data-id="scroll-solution-container" aria-live="polite">
    {cards.map(({id, event}) => <div className="plugin_scroll-solution-toast" key={id}><div className="plugin_scroll-solution-row">
      <div className="score">{event.score}</div><div className="user"><span className="user-name">{event.name}</span>{event.organization && <span className="user-second-name">{event.organization}</span>}</div>
      <div className="problem">{event.alias}</div><div className={`result ${event.result === 'FB' ? 'result-fb' : event.result === 'AC' ? 'result-ac' : event.result === '?' ? 'result-fz' : 'result-rj'}`}><span>{event.result}</span></div>
    </div></div>)}
  </div>;
}

function Board({snapshot, options}) {
  const session = options.session, sessionId = snapshot.sessionId, durationMs = Number(session.durationMs);
  const optionsRef = React.useRef(options); optionsRef.current = options;
  const [settings, setSettings] = React.useState(() => normalizeSettings(readJson(SETTINGS_KEY)));
  const [filter, setFilter] = React.useState(() => normalizeFilter(readJson(FILTER_PREFIX + sessionId)));
  const [playback, setPlayback] = React.useState(() => initialPlayback(session, readJson(PLAYBACK_PREFIX + sessionId)));
  const [clock, setClock] = React.useState(() => ({liveMs: liveElapsed(session), elapsedMs: playback.elapsedMs}));
  const [projection, setProjection] = React.useState(null), [projectionBusy, setProjectionBusy] = React.useState(false), [projectionError, setProjectionError] = React.useState('');
  const [settingsOpen, setSettingsOpen] = React.useState(false), [userPayload, setUserPayload] = React.useState(null);
  const [solutionPayload, setSolutionPayload] = React.useState(null), [problemPayload, setProblemPayload] = React.useState(null);
  const [systemDark, setSystemDark] = React.useState(() => window.matchMedia?.('(prefers-color-scheme: dark)').matches === true);
  const [notice, setNotice] = React.useState(''), [feedEvents, setFeedEvents] = React.useState([]);
  const playbackRef = React.useRef(playback), clockRef = React.useRef(clock), requestSequence = React.useRef(0), pendingProjection = React.useRef(false), failedEvent = React.useRef('');
  const table = React.useRef(null), locatePending = React.useRef(false), previousFeed = React.useRef(null);
  playbackRef.current = playback; clockRef.current = clock;
  const resolvedTheme = settings.theme === 'system' ? systemDark ? 'dark' : 'light' : settings.theme;
  const theme = EnumTheme[resolvedTheme];
  const activeSnapshot = projection || snapshot;
  const presented = React.useMemo(() => presentRanklist(activeSnapshot.ranklist, filter, settings), [activeSnapshot, filter, settings]);
  const data = presented.data, ownIndex = data.rows.findIndex(row => row.user.id === (activeSnapshot.own?.id || OWN_TEAM_ID));
  const organizations = React.useMemo(() => [...new Set(activeSnapshot.ranklist.rows.map(row => text(row.user.organization)).filter(Boolean))].sort((a, b) => a.localeCompare(b)), [activeSnapshot]);
  const markers = activeSnapshot.ranklist.markers || [];
  const rule = actualRule(activeSnapshot.ranklist);
  const prepared = session.startAt === null || session.startAt === undefined;
  const elapsedMs = clock.elapsedMs, liveMs = clock.liveMs;
  const replay = canReplay(session, liveMs);
  const externalUrl = options.externalUrl?.({elapsedMs});

  const requestProjection = React.useCallback((target, eventKey = 'manual') => {
    if (!optionsRef.current.onProject || prepared) return Promise.resolve(null);
    const sequence = ++requestSequence.current, expectedSession = sessionId, expectedInput = snapshot.inputKey;
    pendingProjection.current = true; setProjectionBusy(true); setProjectionError('');
    return Promise.resolve().then(() => optionsRef.current.onProject(target)).then(result => {
      // A live request can be capped by the native snapshot's confirmed clock.
      if (!result || result.sessionId !== expectedSession || result.inputKey !== expectedInput ||
          !Number.isFinite(result.elapsedMs) || result.elapsedMs < 0 || result.elapsedMs > target + 1 ||
          canReplay(optionsRef.current.session, clockRef.current.liveMs) && Math.abs(result.elapsedMs - target) > 1) throw new Error('榜单显示时刻更新失败，请重试。');
      if (sequence === requestSequence.current) {setProjection(result); failedEvent.current = '';}
      return result;
    }).catch(error => {
      if (sequence === requestSequence.current) {failedEvent.current = `${expectedInput}:${eventKey}`; setProjectionError(error.message || '榜单显示时刻更新失败。');}
      return null;
    }).finally(() => {
      if (sequence === requestSequence.current) {pendingProjection.current = false; setProjectionBusy(false);}
    });
  }, [sessionId, snapshot.inputKey, prepared]);

  React.useEffect(() => {
    const media = window.matchMedia?.('(prefers-color-scheme: dark)');
    if (!media) return;
    const update = event => setSystemDark(event.matches);
    media.addEventListener?.('change', update);
    return () => media.removeEventListener?.('change', update);
  }, []);
  React.useEffect(() => {writeJson(SETTINGS_KEY, settings);}, [settings]);
  React.useEffect(() => {writeJson(FILTER_PREFIX + sessionId, filter);}, [filter, sessionId]);
  React.useEffect(() => {
    if (!playback.custom) {removeLocal(PLAYBACK_PREFIX + sessionId); return;}
    writeJson(PLAYBACK_PREFIX + sessionId, {version: 1, startAt: session.startAt, elapsedMs: clockRef.current.elapsedMs,
      playing: playback.playing, speed: playback.speed, custom: true, savedAt: Date.now()});
  }, [playback, sessionId, session.startAt]);
  React.useEffect(() => {
    const tick = () => {
      const now = Date.now(), currentLive = liveElapsed(session, now);
      const next = advancePlayback(playbackRef.current, currentLive, now, durationMs);
      setClock(previous => previous.liveMs === currentLive && previous.elapsedMs === next.elapsedMs ? previous : {liveMs: currentLive, elapsedMs: next.elapsedMs});
      if (!next.playing && playbackRef.current.playing) {
        setPlayback(current => ({...current, playing: false, elapsedMs: next.elapsedMs, anchorAt: now, anchorElapsedMs: next.elapsedMs}));
      }
    };
    tick(); const handle = window.setInterval(tick, 250);
    document.addEventListener('visibilitychange', tick);
    return () => {window.clearInterval(handle); document.removeEventListener('visibilitychange', tick);};
  }, [session, durationMs]);
  React.useEffect(() => {
    failedEvent.current = '';
    if (playbackRef.current.custom) requestProjection(clockRef.current.elapsedMs); else setProjection(null);
  }, [snapshot.inputKey, snapshot.observedAt, requestProjection]);
  React.useEffect(() => {
    const next = activeSnapshot.nextEventMs;
    if (prepared || next === null || next === undefined || elapsedMs < next || pendingProjection.current || document.hidden) return;
    const key = `${activeSnapshot.inputKey}:${next}`;
    if (failedEvent.current === key) return;
    requestProjection(elapsedMs, next);
  }, [elapsedMs, activeSnapshot, prepared, requestProjection]);
  React.useEffect(() => {
    const current = timeline(activeSnapshot.ranklist), previous = previousFeed.current;
    if (previous && settings.feed) {
      const added = feedSolutions(previous.solutions, current, activeSnapshot.elapsedMs > previous.elapsedMs);
      const rows = new Map(activeSnapshot.ranklist.rows.map(row => [String(row.user.id), row]));
      const hidden = new Set(presented.ccpc26Layout?.hiddenProblemIndexes || []);
      setFeedEvents(added.map(solution => {
        const row = rows.get(String(solution[0])), hiddenProblem = hidden.has(solution[1]);
        return {score: row?.score.value || 0, name: text(row?.user.name) || solution[0], organization: text(row?.user.organization),
          alias: hiddenProblem ? '?' : activeSnapshot.ranklist.problems[solution[1]]?.alias || String(solution[1] + 1),
          result: hiddenProblem && solution[2] === 'FB' ? 'AC' : solution[2]};
      }));
    }
    previousFeed.current = {solutions: current, elapsedMs: activeSnapshot.elapsedMs};
  }, [activeSnapshot, settings.feed, presented.ccpc26Layout]);

  const changeSetting = (key, value) => setSettings(current => ({...current, [key]: value}));
  const seek = target => {
    if (!replay) return;
    const now = Date.now(), next = playbackForSeek(playbackRef.current, target, durationMs, now);
    setPlayback(next); setClock({liveMs: liveElapsed(session, now), elapsedMs: next.elapsedMs}); requestProjection(next.elapsedMs);
  };
  const togglePlayback = () => {
    if (!replay) return;
    const now = Date.now(), currentLive = liveElapsed(session, now), currentElapsed = clockRef.current.elapsedMs;
    const next = playbackForToggle(playbackRef.current, currentElapsed, durationMs, now);
    setPlayback(next); setClock({liveMs: currentLive, elapsedMs: next.elapsedMs});
    if (next.custom) requestProjection(next.elapsedMs);
  };
  const followLive = () => {
    const now = Date.now(), current = liveElapsed(session, now);
    setPlayback({custom: false, elapsedMs: current, playing: current < durationMs, speed: playback.speed, anchorAt: now, anchorElapsedMs: current});
    setClock({liveMs: current, elapsedMs: current}); setProjection(null); failedEvent.current = '';
    requestProjection(current);
  };
  const changeSpeed = speed => {
    if (!replay || !SPEEDS.includes(speed)) return;
    const now = Date.now(), current = clockRef.current.elapsedMs;
    setPlayback({...playback, speed, anchorAt: now, anchorElapsedMs: current, elapsedMs: current});
  };
  const locateOwn = () => {
    if (ownIndex < 0) {locatePending.current = true; setFilter(normalizeFilter(null)); return;}
    table.current?.locateOwn();
  };
  React.useEffect(() => {
    if (!locatePending.current || ownIndex < 0) return;
    locatePending.current = false;
    const frame = requestAnimationFrame(() => table.current?.locateOwn());
    return () => cancelAnimationFrame(frame);
  }, [ownIndex]);
  const download = () => {
    const blob = new Blob([JSON.stringify(activeSnapshot.ranklist)], {type: 'application/json;charset=utf-8'});
    const url = URL.createObjectURL(blob), link = document.createElement('a');
    link.href = url; link.download = `${options.contestKey || 'scoreboard'}.srk.json`; document.body.append(link); link.click(); link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 60000); setNotice('已导出当前显示时刻的标准榜单。');
  };
  const share = async () => {
    if (!externalUrl) return;
    try {await navigator.clipboard.writeText(externalUrl); setNotice('外榜链接已复制。');}
    catch (_) {setNotice('无法访问剪贴板，请使用“打开外榜”。');}
  };
  const contest = activeSnapshot.ranklist.contest, range = formatContestTimeRange(contest.startAt, contest.duration);
  const contributors = (activeSnapshot.ranklist.contributors || []).map(resolveContributor).filter(Boolean);
  const refLinks = contest.refLinks || [];
  const activeUser = userPayload && data.rows.find(row => row.user.id === userPayload.user.id)?.user || userPayload?.user;
  const activeProblemRevealed = problemPayload && !(presented.ccpc26Layout?.hiddenProblemIndexes.includes(problemPayload.problemIndex));
  const activeSolution = React.useMemo(() => {
    if (!solutionPayload) return null;
    const row = activeSnapshot.ranklist.rows.find(item => item.user.id === solutionPayload.user.id);
    const status = row?.statuses[solutionPayload.problemIndex];
    return {...solutionPayload, problem: activeSnapshot.ranklist.problems[solutionPayload.problemIndex],
      problemRevealed: !presented.ccpc26Layout?.hiddenProblemIndexes.includes(solutionPayload.problemIndex),
      solutions: status ? [...(status.solutions || [])].reverse() : solutionPayload.solutions};
  }, [solutionPayload, activeSnapshot, presented.ccpc26Layout]);
  React.useEffect(() => {
    if (problemPayload && !activeProblemRevealed) setProblemPayload(null);
  }, [problemPayload, activeProblemRevealed]);
  const playLabel = prepared ? '尚未开始' : !replay ? '比赛进行中' : !playback.custom ? '回放' : playback.playing ? '暂停' : '继续';
  return <section className={`qoj-board qoj-theme-${resolvedTheme}`} data-theme={resolvedTheme} data-id="vp-ranklist-content" data-session-id={sessionId}>
    <div className="qoj-playback-controls">
      <button type="button" className="qoj-button qoj-button-primary" data-id="board-play-toggle" disabled={!replay} onClick={togglePlayback}>{playLabel}</button>
      <label className="qoj-speed" title={replay ? "只改变榜单回放速度" : "赛后可设置回放倍速"}>倍速 <select className="qoj-speed-select" aria-label="虚拟参赛倍速" disabled={!replay} value={playback.speed} onChange={event => changeSpeed(Number(event.target.value))}>
        {SPEEDS.map(value => <option value={value} key={value}>{value}×</option>)}
      </select></label>
      <button type="button" className="qoj-button qoj-button-outline" data-id="board-follow-live" disabled={!playback.custom} onClick={followLive}>回到当前</button>
      <button type="button" className="qoj-button qoj-button-outline" data-id="board-locate-own" onClick={locateOwn}>定位本队</button>
      {playback.custom && <span className="qoj-view-clock-note">仅更改榜单显示，不影响比赛计时</span>}
    </div>
    {prepared && <p className="qoj-prepared-note">比赛尚未开始，打开榜单不会启动计时。</p>}
    <div className="qoj-title-wrap"><h1 className="srk-ranklist-title">{text(contest.title)}</h1>
      {externalUrl && <a className="qoj-rankland-link" data-id="board-open-rankland" href={externalUrl} target="_blank" rel="noopener noreferrer">打开外榜 <Icon name="external" /></a>}
    </div>
    <div className="srk-ranklist-meta">
      <button type="button" className="srk-ranklist-action-menu srk-ranklist-action-trigger" data-id="ranklist-download-action" aria-label="下载当前榜单" onClick={download}><Icon name="download" /></button>
      <span className="srk-ranklist-meta-divider" />
      {externalUrl && <button type="button" className="srk-ranklist-action-menu srk-ranklist-action-trigger" data-id="ranklist-share-action" aria-label="复制外榜链接" onClick={share}><Icon name="share" /></button>}
      {contributors.length > 0 && <p className="srk-ranklist-meta-line">贡献者：{contributors.map((contributor, index) => <React.Fragment key={`${contributor.name}:${index}`}>
        {index > 0 && ', '}{contributor.url && /^https:\/\//.test(contributor.url) ? <a href={contributor.url} target="_blank" rel="noopener noreferrer">{contributor.name}</a> : contributor.name}
      </React.Fragment>)}</p>}
      {refLinks.length > 0 && <p className="srk-ranklist-meta-line">相关链接：{refLinks.slice(0, 3).map((link, index) => <React.Fragment key={`${link.link}:${index}`}>
        {index > 0 && ', '}<a href={link.link} target="_blank" rel="noopener noreferrer">{text(link.title)}</a>
      </React.Fragment>)}</p>}
      {rule === 'CCPC26' && <p className="qoj-ccpc26-note">CCPC 2026 · 动态揭题</p>}
    </div>
    <p className="srk-ranklist-time">{prepared ? '开始时间将在 QOJ 确认后显示' : `${range.startText} ~ ${range.endText}`}</p>
    <div className="qoj-progress" data-id="ranklist-progress"><ViewProgress session={session} playback={playback} elapsedMs={elapsedMs} liveMs={liveMs}
      frozenDuration={contest.frozenDuration} onSeek={seek} /></div>
    <div className="srk-ranklist-toolbar srk-ranklist-toolbar-with-filter">
      <div className="srk-ranklist-filter"><div className="srk-ranklist-filter-primary">
        <label className="srk-ranklist-org-filter"><span className="srk-ranklist-filter-title">筛选</span>
          <OrganizationFilter organizations={organizations} selected={filter.organizations} onChange={organizationsValue => setFilter({...filter, organizations: organizationsValue})} /></label>
        <label className="srk-ranklist-official-filter"><span>仅正式参赛</span><Switch checked={filter.officialOnly} label="仅正式参赛" onChange={value => setFilter({...filter, officialOnly: value})} /></label>
      </div>
      {markers.length > 0 && <ToggleGroup value={filter.marker || '__all__'} values={[['__all__', '全部'], ...markers.map(marker => [marker.id, text(marker.label)])]}
        dataId="ranklist-marker-toggle-group" onChange={value => setFilter({...filter, marker: value === '__all__' ? '' : value})} />}</div>
      <div className="srk-ranklist-actions">
        <span className="qoj-feed-toggle"><span>实时滚动提交状态</span><Switch checked={settings.feed} label="实时滚动提交状态" onChange={value => changeSetting('feed', value)} /></span>
        <button type="button" className="srk-ranklist-icon-button" data-id="ranklist-theme-action" aria-label="切换明暗主题" title={`当前：${resolvedTheme === 'dark' ? '深色' : '浅色'}`}
          onClick={() => changeSetting('theme', resolvedTheme === 'dark' ? 'light' : 'dark')}><Icon name={resolvedTheme === 'dark' ? 'moon' : 'sun'} /></button>
        <button type="button" className="srk-ranklist-icon-button" data-id="ranklist-settings-action" aria-label="榜单偏好设置" onClick={() => setSettingsOpen(true)}><Icon name="settings" /></button>
      </div>
    </div>
    <div className="qoj-board-notices" aria-live="polite">
      {ownIndex < 0 && <p>本队被当前筛选隐藏。<button type="button" onClick={locateOwn}>清除筛选并定位本队</button></p>}
      {projectionError && <p role="alert">{projectionError}</p>}{notice && <p>{notice}</p>}
    </div>
    <div className="qoj-table-gap" />
    {activeSnapshot.ranklist.remarks && <div className="qoj-remarks"><span className="srk-remarks">备注：{text(activeSnapshot.ranklist.remarks)}</span></div>}
    <div className={`srk-ranklist-table-scroll ${projectionBusy ? 'is-projecting' : ''}`} role="region" aria-label="比赛榜单" aria-busy={projectionBusy}>
      <VirtualRanklist ref={table} data={data} ownTeamId={activeSnapshot.own?.id || OWN_TEAM_ID} hideOwnRank={activeSnapshot.own?.rankHidden === true} resetKey={sessionId}
        enableCCPC26={Boolean(presented.ccpc26Layout)} ccpc26ProblemLayout={presented.ccpc26Layout} theme={theme}
        statusCellPreset={settings.statusCellPreset} statusColorAsText={settings.statusColorAsText}
        showProblemStatisticsFooter={settings.professionalMode} showDirtColumn={settings.professionalMode} showSEColumn={settings.professionalMode}
        rowBordered={settings.tableBordered} columnBordered={settings.tableBordered} rowStriped={settings.rowStriped}
        emptyStatusPlaceholder={settings.emptyStatusPlaceholder === 'dot' ? '·' : settings.emptyStatusPlaceholder === 'dash' ? '-' : null}
        splitOrganization={settings.splitOrganization} userAvatarPlacement={settings.userAvatarPlacement} formatSrkAssetUrl={() => ''} languages={LANGUAGES}
        onUserClick={payload => {setUserPayload(payload); setSolutionPayload(null); setProblemPayload(null);}}
        onSolutionClick={payload => {setSolutionPayload(payload); setUserPayload(null); setProblemPayload(null);}}
        onProblemClick={payload => {setProblemPayload(payload); setUserPayload(null); setSolutionPayload(null);}} />
    </div>
    <SettingsModal open={settingsOpen} settings={settings} rule={rule} theme={resolvedTheme} onChange={changeSetting} onClose={() => setSettingsOpen(false)} />
    <DefaultUserModal open={Boolean(userPayload && activeUser)} user={activeUser} markers={markers} theme={theme} languages={LANGUAGES}
      title={activeUser ? text(activeUser.name) : undefined} width={window.innerWidth >= 980 ? 960 : Math.max(window.innerWidth - 20, 280)} rootClassName={`srk-general-modal-root qoj-theme-${resolvedTheme}`} onClose={() => setUserPayload(null)} />
    <DefaultSolutionModal open={Boolean(activeSolution)} user={activeSolution?.user} problem={activeSolution?.problem}
      problemIndex={activeSolution?.problemIndex ?? 0} problemRevealed={activeSolution?.problemRevealed} solutions={activeSolution?.solutions || []}
      languages={LANGUAGES} width={420} rootClassName={`srk-general-modal-root qoj-theme-${resolvedTheme}`} onClose={() => setSolutionPayload(null)} />
    <Modal open={Boolean(problemPayload && activeProblemRevealed)} title={problemPayload ? `Info of Problem ${problemPayload.problem.alias || problemPayload.problemIndex + 1}` : undefined}
      width={680} rootClassName={`srk-general-modal-root qoj-theme-${resolvedTheme}`} onClose={() => setProblemPayload(null)}>
      {problemPayload && activeProblemRevealed && <ProblemDetails problem={problemPayload.problem} problemIndex={problemPayload.problemIndex} ranklist={activeSnapshot.ranklist} />}
    </Modal>
    <SubmissionFeed events={feedEvents} enabled={settings.feed} />
  </section>;
}

export function render(element, snapshot, options = {}) {
  let root = roots.get(element);
  if (!root) {root = createRoot(element); roots.set(element, root);}
  root.render(<Board key={snapshot.sessionId} snapshot={snapshot} options={options} />);
}

export function clear(element) {
  const root = roots.get(element);
  if (root) {root.unmount(); roots.delete(element);}
}

export {normalizeSettings, normalizeFilter, initialPlayback, advancePlayback, feedSolutions, uniformRowWindow,
  liveElapsed, playbackForSeek, playbackForToggle, presentRanklist, formatClock, formatContestTimeRange} from './view-model.js';
