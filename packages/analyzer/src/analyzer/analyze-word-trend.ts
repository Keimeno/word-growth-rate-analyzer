import {config} from '@keimeno/wgra-common';
import {addDays, endOfDay, startOfDay, subDays} from 'date-fns';
import {DailyScrapedWordCount} from '../models';

export interface DailyWordFrequency {
  date: Date;
  count: number;
  baselineCount: number;

  /**
   * Occurrences of the word per occurrence of the baseline word. Since the
   * baseline grows and shrinks with the user activity of the subreddit,
   * this removes fluctuations between peak hours and week days.
   */
  relativeFrequency: number;
}

export interface WordTrend {
  word: string;
  subreddit: string;
  baseline: string;
  days: DailyWordFrequency[];

  /**
   * Day to day growth rates of the relative frequency, 1.2 means +20%.
   */
  growthRates: number[];

  /**
   * Growth of the relative frequency between the first and the last day.
   */
  sustainableGrowthRate: number;
}

const getCount = async (word: string, subreddit: string, date: Date) => {
  const scrapedWordCount = await DailyScrapedWordCount.findOne({
    word,
    subreddit,
    createdAt: {$gte: startOfDay(date), $lte: endOfDay(date)},
  });

  return scrapedWordCount?.count ?? null;
};

interface AnalyzeDayToDayWordTrendOptions {
  from: Date;
  to?: Date;
  subreddit: string;
}

export const analyzeDayToDayWordTrend = async (
  word: string,
  {from, to = new Date(), subreddit}: AnalyzeDayToDayWordTrendOptions
): Promise<WordTrend> => {
  const subredditConfig = config.subreddits.find(
    ({name}) => name === subreddit
  );
  const baseline = subredditConfig?.baseline ?? 'the';

  // counts at or below the threshold are deleted by the free storage job,
  // so a missing count means the word occurred at most `threshold` times
  const missingCount = subredditConfig?.threshold ?? 0;

  const days: DailyWordFrequency[] = [];

  for (
    let date = startOfDay(from);
    date <= startOfDay(to);
    date = addDays(date, 1)
  ) {
    const [count, baselineCount] = await Promise.all([
      getCount(word, subreddit, date),
      getCount(baseline, subreddit, date),
    ]);

    // without the baseline we didn't scrape on that day
    if (baselineCount === null) {
      continue;
    }

    const wordCount = count ?? missingCount;
    days.push({
      date,
      count: wordCount,
      baselineCount,
      relativeFrequency: wordCount / baselineCount,
    });
  }

  const growthRates = days
    .slice(1)
    .map((day, index) => day.relativeFrequency / days[index].relativeFrequency);

  const sustainableGrowthRate = growthRates.reduce(
    (sustainableGrowthRate, growthRate) => sustainableGrowthRate * growthRate,
    1
  );

  return {word, subreddit, baseline, days, growthRates, sustainableGrowthRate};
};

export const analyzeRecentWordTrend = (
  word: string,
  subreddit: string,
  numberOfDays: number
) =>
  analyzeDayToDayWordTrend(word, {
    subreddit,
    from: subDays(new Date(), numberOfDays - 1),
  });
