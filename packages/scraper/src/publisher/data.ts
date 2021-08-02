import {ScrapedWordCount} from '@keimeno/wgra-common';
import {DailyScrapedWordCount} from '../models';
import {overviewState} from '../state';
import {flattenDate} from '../utils';

const scrapedWordsCount: ScrapedWordCount[] = [];

// using a placeholder date instead of creating a new date for every record
// will save us a lot of memory
const placeholderDate = new Date();

export const incrementScrapedWordCount = (subreddit: string, word: string) => {
  // check if there's already a ScrapedWordCount object in the
  // scraped words count array
  // ignore the createdAt date
  const index = scrapedWordsCount.findIndex(
    wordCount => wordCount.word === word && wordCount.subreddit === subreddit
  );

  // item found, increment
  if (index !== -1) {
    scrapedWordsCount[index].count++;
    return;
  }

  // item not found, create new object with count 1
  scrapedWordsCount.push({
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

    // create a deep clone of scrapedWordsCount
    // a clone must be created and the scrapedWordsCount
    // must be emptied later on, this has to be done since all upserts
    // are running one by one. This would otherwise cause a concurrency issue
    const wordsCount: ScrapedWordCount[] = JSON.parse(
      JSON.stringify(scrapedWordsCount)
    );

    // empty scraped words count
    scrapedWordsCount.length = 0;

    for (let i = 0; i < wordsCount.length; i++) {
      const {word, count, subreddit} = wordsCount[i];
      await DailyScrapedWordCount.updateOne(
        {word, createdAt, subreddit},
        {$inc: {count}},
        {upsert: true}
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
    const scrapedWordsCountGrouped = wordsCount.reduce<any>(
      (accumulator, currentValue) => {
        const {subreddit, count} = currentValue;
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
