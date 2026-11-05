import React from 'react';
import {
  calculateProblemStatisticsFooter,
  formatProblemStatisticsAcceptedMinute,
  formatProblemStatisticsAverageHardness,
  formatProblemStatisticsPercent,
  formatSolutionTimestamp,
  getSolutionResultMeta,
} from '@algoux/standard-ranklist-renderer-component-core';
import {numberToAlphabet, resolveText} from '@algoux/standard-ranklist-utils';
import {LANGUAGES, timeline} from './view-model.js';

const PAGE_SIZE = 5;

export function ProblemDetails({problem, problemIndex, ranklist}) {
  const [page, setPage] = React.useState(1);
  const alias = problem.alias || numberToAlphabet(problemIndex);
  const title = resolveText(problem.title, LANGUAGES) || `Problem ${alias}`;
  const statistics = calculateProblemStatisticsFooter(ranklist)[problemIndex];
  const solutions = React.useMemo(() => timeline(ranklist).filter(item => item[1] === problemIndex).reverse(), [ranklist, problemIndex]);
  const users = React.useMemo(() => new Map(ranklist.rows.map(row => [String(row.user.id), row.user])), [ranklist]);
  const pageCount = Math.max(1, Math.ceil(solutions.length / PAGE_SIZE));
  React.useEffect(() => {setPage(1);}, [problemIndex]);
  React.useEffect(() => {if (page > pageCount) setPage(pageCount);}, [page, pageCount]);
  const visible = solutions.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  const metrics = statistics ? [
    ['Accepted', String(statistics.accepted), formatProblemStatisticsPercent(statistics.accepted, statistics.participantCount), 'Number of participants who solved this problem'],
    ['Attempted', String(statistics.attempted), formatProblemStatisticsPercent(statistics.attempted, statistics.participantCount), 'Number of participants who attempted this problem'],
    ['Submitted', String(statistics.submitted), undefined, 'Total number of valid submissions for this problem'],
    ['Dirt', String(statistics.dirt), formatProblemStatisticsPercent(statistics.dirt, statistics.dirtSubmitted), 'Wrong submissions among participants who solved this problem'],
    ['SE', formatProblemStatisticsAverageHardness(statistics), undefined, 'Average hardness'],
    ['FB/LB at', `${formatProblemStatisticsAcceptedMinute(statistics.firstAcceptedTime)}/${formatProblemStatisticsAcceptedMinute(statistics.lastAcceptedTime)}`,
      statistics.firstAcceptedTime || statistics.lastAcceptedTime ? 'min' : undefined, 'First and last accepted time'],
  ] : [];
  return <div className="problem-modal">
    <div className="problem-modal-info">
      {problem.link && /^https:\/\//.test(problem.link) ?
        <a className="problem-modal-title-link" href={problem.link} target="_blank" rel="noopener noreferrer">
          <span className="problem-modal-title">{title}</span><span aria-hidden="true"> ↗</span>
        </a> : <span className="problem-modal-title">{title}</span>}
    </div>
    <div className="problem-modal-stats">
      {metrics.map(([label, primary, secondary, tooltip]) => <div className="problem-modal-stat" title={tooltip} key={label}>
        <div className="problem-modal-stat-label">{label}</div><div className="problem-modal-stat-primary">{primary}</div>
        {secondary !== undefined && <div className="problem-modal-stat-secondary">{secondary}</div>}
      </div>)}
    </div>
    <div className="problem-modal-submissions">
      <table className="srk-common-table srk-solutions-table problem-modal-submissions-table">
        <thead><tr><th className="srk--text-left">User</th><th className="srk--text-left">Result</th><th className="srk--text-right">Time</th></tr></thead>
        <tbody>
          {visible.map((solution, index) => {
            const user = users.get(String(solution[0])), meta = getSolutionResultMeta(solution[2]);
            return <tr key={`${solution[0]}:${solution[2]}:${solution[3][0]}:${index}`}>
              <td><div className="problem-modal-submission-user">{resolveText(user?.name, LANGUAGES) || solution[0]}</div>
                {user?.organization && <div className="problem-modal-submission-org">{resolveText(user.organization, LANGUAGES)}</div>}</td>
              <td><span className={`srk-solution-result-text ${meta.className || ''}`}>{meta.label}</span></td>
              <td className="srk--text-right">{formatSolutionTimestamp({result: solution[2], time: solution[3]})}</td>
            </tr>;
          })}
          {!solutions.length && <tr><td colSpan="3" className="srk--text-center problem-modal-submissions-empty">暂无提交记录</td></tr>}
        </tbody>
      </table>
      {pageCount > 1 && <nav className="problem-modal-pagination" aria-label="提交分页">
        <button type="button" disabled={page === 1} onClick={() => setPage(value => value - 1)}>上一页</button>
        <span>{page} / {pageCount}</span>
        <button type="button" disabled={page === pageCount} onClick={() => setPage(value => value + 1)}>下一页</button>
      </nav>}
    </div>
  </div>;
}
