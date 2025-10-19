import {flattenDate, ScrapedWordCount} from '@keimeno/wgra-common';
import {DailyScrapedWordCount} from '../models';
import {overviewState} from '../state';

// keyed by subreddit and word, a map keeps the increment O(1) even with
// tens of thousands of unique words per minute
let scrapedWordsCount = new Map<string, ScrapedWordCount>();

// using a placeholder date instead of creating a new date for every record
// will save us a lot of memory
const placeholderDate = new Date();

export const incrementScrapedWordCount = (subreddit: string, word: string) => {
  const key = `${subreddit}\u0000${word}`;
  const wordCount = scrapedWordsCount.get(key);

  // item found, increment
  if (wordCount !== undefined) {
    wordCount.count++;
    return;
  }

  // item not found, create new object with count 1
  scrapedWordsCount.set(key, {
    word,
    subreddit,
    count: 1,
    createdAt: placeholderDate,
  });
};

const upsertScrapedWordsCount = async () => {
  try {
    // in order to remove inconsistencies between lesser occurring words,
    // we must overwrite the createdAt date
    const createdAt = flattenDate(new Date());

    // swap out the map before writing, so that words counted while the
    // upsert is running end up in the next batch
    const wordsCount = [...scrapedWordsCount.values()];
    scrapedWordsCount = new Map();

    if (wordsCount.length > 0) {
      await DailyScrapedWordCount.bulkWrite(
        wordsCount.map(({word, count, subreddit}) => ({
          updateOne: {
            filter: {word, createdAt, subreddit},
            update: {$inc: {count}},
            upsert: true,
          },
        })),
        {ordered: false}
      );
    }

    const trueAmountWords = wordsCount.reduce(
      (accumulator, currentValue) => accumulator + currentValue.count,
      0
    );
    const hhmmss = new Date().toTimeString().split(' ')[0];

    overviewState.totalProcessedWordCount += trueAmountWords;
    overviewState.totalProcessedUniqueWordCount += wordsCount.length;

    // sum up the scraped words count and group by subreddit
    const scrapedWordsCountGrouped = wordsCount.reduce(
      (accumulator, {subreddit, count}) => {
        if (!accumulator[subreddit]) {
          accumulator[subreddit] = count;
        } else {
          accumulator[subreddit] += count;
        }
        return accumulator;
      },
      {}
    );

    console.log(scrapedWordsCountGrouped);

    console.log(
      `[${hhmmss}] Successfully upserted ${wordsCount.length} unique words and ${trueAmountWords} words in total`
    );
  } catch (e) {
    console.log('Failed to upsert scrapedWordsCount', e);
  }
};

// upsert every minute
setInterval(() => upsertScrapedWordsCount(), 1000 * 60);
