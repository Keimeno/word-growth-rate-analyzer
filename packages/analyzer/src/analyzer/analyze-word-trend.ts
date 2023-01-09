import {flattenDate, ScrapedWordCount} from '@keimeno/wgra-common';
import {startOfDay, endOfDay} from 'date-fns';
import {DailyScrapedWordCount} from '../models';

const getFirstOccurrence = async (
  word: string,
  subreddit?: string
): Promise<ScrapedWordCount | null> => {
  const firstOccurrence = await DailyScrapedWordCount.findOne(
    {word, ...(subreddit !== undefined ? {subreddit} : {})},
    {},
    {sort: {createdAt: 1}}
  );

  return firstOccurrence;
};

const getFirstCreatedAt = async (
  word: string,
  subreddit?: string
): Promise<Date> => {
  const firstOccurrence = await getFirstOccurrence(word, subreddit);

  if (!firstOccurrence) {
    throw new Error('No first occurrence found.');
  }

  return firstOccurrence.createdAt;
};

const getScrapedWordCount = async (
  word: string,
  date: Date,
  subreddit?: string
): Promise<ScrapedWordCount | null> => {
  const scrapedWordCount = await DailyScrapedWordCount.findOne({
    word,
    createdAt: {$gte: startOfDay(date), $lt: endOfDay(date)},
    ...(subreddit !== undefined ? {subreddit} : {}),
  });

  return scrapedWordCount;
};

interface BaselineAdjustedCountsOptions {
  from: Date;
  to: Date;
  baseline: string;
  subreddit?: string;
  previousWordCounts?: number[];
  previousBaselineCount?: number;
}

const getBaselineAdjustedCounts = async (
  word: string,
  {
    from,
    to,
    baseline,
    subreddit = undefined,
    previousBaselineCount = undefined,
    previousWordCounts = [],
  }: BaselineAdjustedCountsOptions
): Promise<number[]> => {
  if (from.getTime() === to.getTime()) {
    // get relative growth rate of word counts
    return previousWordCounts;
  }

  const scrapedWordCount = await getScrapedWordCount(word, from, subreddit);
  const baselineScrapedWordCount = await getScrapedWordCount(
    baseline,
    from,
    subreddit
  );

  const baselineScrapedWordCountCount =
    baselineScrapedWordCount === null ? 50 : baselineScrapedWordCount.count;

  const scrapedWordCountCount =
    scrapedWordCount === null ? 50 : scrapedWordCount.count;

  const userActivityMultiplier =
    baselineScrapedWordCountCount /
    (previousBaselineCount ?? baselineScrapedWordCountCount);

  const nextDay = new Date(from);
  nextDay.setDate(nextDay.getDate() + 1);

  return await getBaselineAdjustedCounts(word, {
    from: flattenDate(nextDay),
    to,
    subreddit,
    baseline,
    previousBaselineCount: baselineScrapedWordCountCount,
    previousWordCounts: [
      ...previousWordCounts,
      scrapedWordCountCount * userActivityMultiplier,
    ],
  });
};

const calculateGrowthRates = (counts: number[]): number[] => {
  // calculate growth rates in a functional way
  return counts.reduce<number[]>(
    (growthRates, count, index, originalCounts) => {
      if (index === 0) {
        return growthRates;
      }

      return [...growthRates, count / originalCounts[index - 1]];
    },
    []
  );
};

interface AnalyzeDayToDayWordTrendOptions {
  from?: Date;
  to?: Date;
  subreddit?: string;
}

export const analyzeDayToDayWordTrend = async (
  word: string,
  {from, to, subreddit}: AnalyzeDayToDayWordTrendOptions = {}
) => {
  const startDate =
    from !== undefined
      ? flattenDate(from)
      : await getFirstCreatedAt(word, subreddit);
  const endDate = flattenDate(to ?? new Date());

  const baselineAdjustedCounts = await getBaselineAdjustedCounts(word, {
    from: startDate,
    to: endDate,
    subreddit,
    baseline: 'the',
  });

  const growthRates = calculateGrowthRates(baselineAdjustedCounts);

  const sustainableGrowthRate = growthRates.reduce<number>(
    (sustainableGrowthRate, growthRate) => sustainableGrowthRate * growthRate,
    1
  );

  return sustainableGrowthRate;
};

analyzeDayToDayWordTrend('christmas', {
  subreddit: 'news',
  from: new Date('2022-12-09'),
  to: new Date('2022-12-26'),
});
