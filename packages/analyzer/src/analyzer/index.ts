import {format} from 'date-fns';
import {connection, redis} from '../infrastructure';
import {analyzeRecentWordTrend} from './analyze-word-trend';

export * from './analyze-word-trend';

const formatPercent = (growthRate: number) =>
  `${growthRate >= 1 ? '+' : ''}${((growthRate - 1) * 100).toFixed(1)}%`;

// usage: node dist/index.js <word> [subreddit=all] [days=7]
const main = async () => {
  const [word, subreddit = 'all', days = '7'] = process.argv.slice(2);

  if (!word) {
    console.error('usage: node dist/index.js <word> [subreddit] [days]');
    process.exitCode = 1;
    return;
  }

  const trend = await analyzeRecentWordTrend(
    word.toLowerCase(),
    subreddit,
    Number(days)
  );

  console.log(
    `"${trend.word}" in r/${trend.subreddit} (baseline "${trend.baseline}")`
  );
  console.table(
    trend.days.map((day, index) => ({
      day: format(day.date, 'yyyy-MM-dd'),
      count: day.count,
      baseline: day.baselineCount,
      'per 1k baseline': +(day.relativeFrequency * 1000).toFixed(3),
      growth: index === 0 ? '' : formatPercent(trend.growthRates[index - 1]),
    }))
  );
  console.log(`overall growth: ${formatPercent(trend.sustainableGrowthRate)}`);
};

main()
  .catch(e => {
    console.error(e);
    process.exitCode = 1;
  })
  .finally(() => {
    connection.close();
    redis.disconnect();
  });
