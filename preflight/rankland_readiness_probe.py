"""Read-only, credential-free RankLand readiness evidence for a supplied driver.

This module does not open tabs, click controls, write storage, or submit source.
It deliberately returns no team/account names, full URLs, arbitrary page text,
manual submission records, cookies, or unknown query parameters.
"""

from __future__ import annotations


def inspect_rankland_readiness(driver):
    """Call with the driver already on the affected original-site RankLand tab."""
    return driver.execute_script(r"""
      const url = new URL(location.href), q = url.searchParams;
      const shown = e => !!e && !!e.getClientRects().length;
      const enabled = e => shown(e) && !e.disabled;
      const buttons = [...document.querySelectorAll('button')];
      const labels = ['加入我的队伍', '修改队伍信息', '记录提交', '暂停',
        '继续虚拟参赛', '开始虚拟参赛', '比赛结束', '等待预约开始', '返回选赛配置'];
      const controls = Object.fromEntries(labels.map(label => [label,
        buttons.filter(e => enabled(e) && e.textContent.trim() === label).length]));
      const intros = [...document.querySelectorAll('.srk-ranklist-settings-intro-wrap')];
      const problem = [...document.querySelectorAll('select[aria-label="题目"]')];
      const result = [...document.querySelectorAll('select[aria-label="结果"]')];
      const slots = [];
      let storageAvailable = true, introRead = false;
      try {
        introRead = localStorage.getItem('StyledRanklistSettingsIntroRead') === 'true';
        const run = q.get('run');
        if (run) for (const key of Object.keys(localStorage)) {
          if (!key.startsWith('RanklandVP2:') || !key.includes(':' + run + ':')) continue;
          try {
            const value = JSON.parse(localStorage.getItem(key));
            slots.push({parseable: true, version: value?.version,
              running: value?.running === true,
              elapsed: Number.isFinite(value?.elapsed) ? value.elapsed : null,
              ownNameNonempty: typeof value?.ownName === 'string' && !!value.ownName.trim(),
              manualCount: Array.isArray(value?.manual) ? value.manual.length : null});
          } catch (_) { slots.push({parseable: false}); }
        }
      } catch (_) { storageAvailable = false; }
      const error = [...document.querySelectorAll('section.mt-16.text-center > p[role="alert"]')]
        .find(shown);
      return {schema: 'qoj-rankland-readiness-v1',
        origin: url.origin, path: url.pathname, readyState: document.readyState,
        query: Object.fromEntries(['contest', 'run', 'rule', 'count', 'ratio', 'at', 'from', 'play']
          .map(key => [key, q.get(key)])),
        teamInUrl: !!q.get('team')?.trim(),
        boardPresent: !!document.querySelector('[data-id="vp-ranklist-content"]'),
        problemSelects: problem.length, problemSelectsVisible: problem.filter(shown).length,
        problemOptionCount: problem[0]?.options.length ?? null,
        resultSelects: result.length, resultSelectsVisible: result.filter(shown).length,
        introCount: intros.length, introVisible: intros.filter(shown).length,
        introRead, controls, storageAvailable, slots,
        sourceError: !!error,
        sourceErrorKind: !error ? null : error.textContent.trim() === '起始时间必须小于比赛时长。'
          ? 'START_OFFSET_OUT_OF_RANGE' : 'SOURCE_LOAD_ERROR',
        scripts: [...document.scripts].filter(e => e.src)
          .map(e => new URL(e.src).pathname).filter(path => path.startsWith('/assets/'))};
    """)
