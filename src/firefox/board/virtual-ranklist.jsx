import React from 'react';
import {Ranklist} from '../../../vendor/standard-ranklist-renderer-component/packages/react/src/main.ts';
import {getRanklistColumnWidths} from '../../../vendor/rankland-web/src/client/components/ranklist/ranklist-column-widths.ts';
import {
  LARGE_RANKLIST_THRESHOLD,
  RANKLIST_ROW_HEIGHT,
  initialRowWindow,
  uniformRowWindow,
} from './view-model.js';

// Keep upstream numeric ranks for ordering; adapt only the frozen own-rank cells.
class WorkbenchRanklist extends Ranklist {
  constructor(props) {
    super(props);
    const renderRank = this.renderSingleSeriesBody;
    this.renderSingleSeriesBody = (rank, series, row) => {
      if (!this.props.hideOwnRank || row.user.id !== this.props.ownTeamId) return renderRank(rank, series, row);
      return React.cloneElement(renderRank({...rank, rank: null, segmentIndex: null}, series, row),
        {title: '封榜期间排名待揭晓。'}, '?');
    };
  }
}
const MemoRanklist = React.memo(WorkbenchRanklist);
const NUMERIC_PADDING = 2;

export function ranklistColumnWidths(props, availableWidth) {
  const widths = getRanklistColumnWidths(props), data = props.data;
  const nameColumn = data.series.length + (props.splitOrganization ? 1 : 0);
  widths[nameColumn + 1] = Math.max(56, widths[nameColumn + 1]);
  if (data.rows.some(row => row.score?.time)) widths[nameColumn + 2] = Math.max(56, widths[nameColumn + 2]);
  const currentWidth = widths.reduce((sum, width) => sum + width, 0), extra = Math.max(0, Math.floor((availableWidth || 0) - currentWidth));
  if (extra && data.problems.length) {
    const trailing = Number(Boolean(props.showDirtColumn)) + Number(Boolean(props.showSEColumn));
    const start = widths.length - trailing - data.problems.length, share = Math.floor(extra / data.problems.length);
    for (let index = 0; index < data.problems.length; index++) widths[start + index] += share + (index < extra % data.problems.length ? 1 : 0);
  }
  return widths;
}

export const VirtualRanklist = React.forwardRef(function VirtualRanklist(props, ref) {
  const {data, ownTeamId, resetKey} = props;
  const root = React.useRef(null), frame = React.useRef(0), measureRef = React.useRef(null), ownRow = React.useRef(null);
  const windowed = data.rows.length > LARGE_RANKLIST_THRESHOLD;
  const [range, setRange] = React.useState(() => initialRowWindow(data.rows.length));
  const [availableWidth, setAvailableWidth] = React.useState(() => Math.max(0, window.innerWidth - 32));
  const widths = React.useMemo(() => ranklistColumnWidths(props, availableWidth), [data, availableWidth, props.statusCellPreset,
    props.splitOrganization, props.showProblemStatisticsFooter, props.showDirtColumn, props.showSEColumn,
    props.enableCCPC26, props.ccpc26ProblemLayout, props.columnTitles]);
  const nameColumn = data.series.length + (props.splitOrganization ? 1 : 0);
  const fixedWidth = widths.reduce((sum, width) => sum + width, 0);
  const style = {
    '--ranklist-numeric-padding-x': `${NUMERIC_PADDING}px`,
    '--ranklist-window-fixed-width': `${fixedWidth}px`,
    '--ranklist-window-name-width': `${widths[nameColumn]}px`,
  };
  const measure = () => {
    if (!root.current) return;
    const width = root.current.parentElement?.clientWidth;
    if (width > 0) setAvailableWidth(previous => previous === width ? previous : width);
    if (!windowed) return;
    const body = root.current.querySelector('.srk-main > table > tbody');
    const first = body?.rows[0];
    if (!first) return;
    let viewportTop = 0, viewportBottom = window.innerHeight;
    for (let parent = root.current.parentElement; parent && parent !== document.body; parent = parent.parentElement) {
      const overflow = window.getComputedStyle(parent).overflowY;
      if (/auto|scroll/.test(overflow) && parent.scrollHeight > parent.clientHeight + 1) {
        const rect = parent.getBoundingClientRect();
        viewportTop = Math.max(viewportTop, rect.top + parent.clientTop);
        viewportBottom = Math.min(viewportBottom, rect.top + parent.clientTop + parent.clientHeight);
      }
    }
    const bounds = first.getBoundingClientRect();
    const next = uniformRowWindow(body.rows.length, bounds.top, bounds.height, viewportTop, viewportBottom);
    setRange(previous => next.start === previous.start && next.end === previous.end ? previous : next);
  };
  measureRef.current = measure;
  const scheduleMeasure = React.useCallback(() => {
    if (frame.current) return;
    frame.current = window.requestAnimationFrame(() => {frame.current = 0; measureRef.current?.();});
  }, []);
  React.useEffect(() => {
    const observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(scheduleMeasure) : null;
    if (root.current) observer?.observe(root.current);
    window.addEventListener('scroll', scheduleMeasure, {capture: true, passive: true});
    window.addEventListener('resize', scheduleMeasure, {passive: true});
    scheduleMeasure();
    return () => {
      observer?.disconnect(); window.cancelAnimationFrame(frame.current);
      window.removeEventListener('scroll', scheduleMeasure, true);
      window.removeEventListener('resize', scheduleMeasure);
    };
  }, [scheduleMeasure]);
  React.useEffect(scheduleMeasure, [data, windowed, widths, scheduleMeasure]);
  React.useEffect(() => {setRange(initialRowWindow(data.rows.length)); scheduleMeasure();}, [resetKey]);
  const ownIndex = data.rows.findIndex(row => row.user.id === ownTeamId);
  React.useLayoutEffect(() => {
    ownRow.current?.classList.remove('qoj-own-row');
    ownRow.current?.removeAttribute('data-own-team');
    ownRow.current = ownIndex >= 0 ? root.current?.querySelector(`tbody > tr[data-row-index="${ownIndex}"]`) : null;
    ownRow.current?.classList.add('qoj-own-row');
    ownRow.current?.setAttribute('data-own-team', 'true');
  }, [data, ownIndex, range]);
  React.useImperativeHandle(ref, () => ({
    locateOwn() {
      if (ownIndex < 0 || !root.current) return false;
      root.current.querySelector(`tbody > tr[data-row-index="${ownIndex}"]`)?.scrollIntoView({block: 'center', inline: 'nearest', behavior: 'smooth'});
      return true;
    },
  }), [ownIndex]);
  return <div ref={root} className="ranklist-window" style={style} data-windowed={windowed ? 'true' : 'false'}>
    <MemoRanklist {...props} rowWindow={windowed ? range : undefined} retainUserText={windowed}
      columnWidths={widths} rowHeight={RANKLIST_ROW_HEIGHT} />
  </div>;
});
