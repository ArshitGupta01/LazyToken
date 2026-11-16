// Shared by the mobile report renderer and its Node tests. No network or DOM.
((root) => {
  'use strict';
  const criteria = [
    'accuracy',
    'completeness',
    'relevance',
    'clarity',
    'instruction_following',
    'usefulness'
  ];
  const average = (values) =>
    values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
  const finite = (value) => typeof value === 'number' && Number.isFinite(value) && value >= 0;
  const normalize = (value) =>
    Array.isArray(value)
      ? value.map(normalize)
      : value && typeof value === 'object'
        ? Object.fromEntries(
            Object.keys(value)
              .sort()
              .map((key) => [key, normalize(value[key])])
          )
        : value;
  const stable = (value) => JSON.stringify(normalize(value));

  function summarize(report) {
    if (
      report.schema !== 'toksmart-prompt-benchmark-v1' ||
      !Array.isArray(report.runs) ||
      report.runs.length > 10000
    ) {
      throw Error('Choose a JSON export from the TokSmart prompt benchmark runner.');
    }
    const ids = new Set();
    const groups = new Map();
    let measured = 0;
    let tokens = 0;
    for (const run of report.runs) {
      if (
        !run ||
        typeof run.run_id !== 'string' ||
        ids.has(run.run_id) ||
        !['normal', 'lite', 'pro', 'coding'].includes(run.mode) ||
        !['success', 'failed'].includes(run.status) ||
        !['model', 'provider', 'experiment_id', 'task_id', 'prompt_version', 'prompt_sha'].every(
          (key) => typeof run[key] === 'string'
        ) ||
        !Number.isInteger(run.trial) ||
        run.trial < 1 ||
        !finite(run.elapsed_seconds) ||
        !run.settings ||
        typeof run.settings !== 'object' ||
        Array.isArray(run.settings)
      ) {
        throw Error('The report contains an invalid or duplicate run.');
      }
      ids.add(run.run_id);
      if (run.usage_source === 'provider') {
        if (
          ![run.input_tokens, run.output_tokens, run.total_tokens].every(
            (n) => Number.isSafeInteger(n) && n >= 0
          ) ||
          run.total_tokens !== run.input_tokens + run.output_tokens
        )
          throw Error('Invalid provider token totals.');
        measured++;
        tokens += run.total_tokens;
      }
      if (run.cost !== null && run.cost !== undefined && !finite(run.cost))
        throw Error('Invalid cost.');
      if (run.evaluation) {
        if (
          !['manual', 'ai'].includes(run.evaluation.kind) ||
          !criteria.every(
            (key) => finite(run.evaluation.scores?.[key]) && run.evaluation.scores[key] <= 10
          )
        ) {
          throw Error('Quality scores must contain all six criteria, from 0 to 10.');
        }
      }
      const key = JSON.stringify([
        run.experiment_id,
        run.model,
        run.provider,
        stable(run.settings),
        run.prompt_version,
        stable(run.tools || [])
      ]);
      if (!groups.has(key))
        groups.set(key, { model: run.model, experiment: run.experiment_id, pairs: new Map() });
      const group = groups.get(key);
      const pair = `${run.task_id}:${run.trial}`;
      if (!group.pairs.has(pair)) group.pairs.set(pair, {});
      if (group.pairs.get(pair)[run.mode]) throw Error('Duplicate mode in a matched trial.');
      group.pairs.get(pair)[run.mode] = run;
    }
    const summaries = [];
    for (const group of groups.values()) {
      const modes = ['normal', 'lite', 'pro'];
      const eligible = [...group.pairs.values()].filter(
        (pair) =>
          modes.every(
            (mode) => pair[mode]?.status === 'success' && pair[mode].usage_source === 'provider'
          ) &&
          new Set(
            modes.map((mode) =>
              stable({
                task: pair[mode].task,
                context: pair[mode].context,
                followups: pair[mode].followups,
                expected: pair[mode].expected
              })
            )
          ).size === 1
      );
      if (!eligible.length) continue;
      // A prompt must be unchanged within one experiment before pooling its trials.
      if (modes.some((mode) => new Set(eligible.map((pair) => pair[mode].prompt_sha)).size !== 1))
        continue;
      const qualityPairs = eligible.filter(
        (pair) =>
          modes.every((mode) => pair[mode].evaluation) &&
          new Set(
            modes.map(
              (mode) => `${pair[mode].evaluation.kind}:${pair[mode].evaluation.evaluator || ''}`
            )
          ).size === 1
      );
      const costPairs = eligible.filter((pair) => modes.every((mode) => finite(pair[mode].cost)));
      const arms = modes.map((mode) => {
        const quality = average(
          qualityPairs.map((pair) =>
            average(criteria.map((key) => pair[mode].evaluation.scores[key]))
          )
        );
        return {
          mode,
          input: average(eligible.map((p) => p[mode].input_tokens)),
          output: average(eligible.map((p) => p[mode].output_tokens)),
          total: average(eligible.map((p) => p[mode].total_tokens)),
          seconds: average(eligible.map((p) => p[mode].elapsed_seconds)),
          quality,
          cost: average(costPairs.map((p) => p[mode].cost))
        };
      });
      const baseline = arms[0];
      for (const arm of arms) {
        arm.savings =
          baseline.total > 0 ? ((baseline.total - arm.total) / baseline.total) * 100 : null;
        arm.qualityDifference =
          arm.quality !== null && baseline.quality !== null ? arm.quality - baseline.quality : null;
        arm.costSavings =
          baseline.cost > 0 ? ((baseline.cost - arm.cost) / baseline.cost) * 100 : null;
      }
      summaries.push({
        model: group.model,
        experiment: group.experiment,
        pairs: eligible.length,
        qualityPairs: qualityPairs.length,
        costPairs: costPairs.length,
        arms
      });
    }
    return {
      totalRuns: report.runs.length,
      failed: report.runs.filter((r) => r.status === 'failed').length,
      measured,
      tokens,
      groups: summaries
    };
  }
  const api = { summarize, criteria };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.TokSmartMetrics = api;
})(globalThis);
