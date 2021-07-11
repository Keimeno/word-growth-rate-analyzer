import {
  generateDailyScrapedWordCountModel,
  ScrapedWordCount,
} from '@keimeno/wgra-common';
import {connection} from '../infrastructure';

const DailyScrapedWordCount = generateDailyScrapedWordCountModel(connection);
DailyScrapedWordCount.init();

const scrapedWordsCount: ScrapedWordCount[] = [];

// using a placeholder date instead of creating a new date for every record
// will save us a lot of memory
const placeholderDate = new Date();

export const incrementScrapedWordCount = (word: string) => {
  // check if there's already a ScrapedWordCount object in the
  // scraped words count array
  // ignore the createdAt date
  const index = scrapedWordsCount.findIndex(
    wordCount => wordCount.word === word
  );

  // item found, increment
  if (index !== -1) {
    scrapedWordsCount[index].count++;
    return;
  }

  // item not found, create new object with count 1
  scrapedWordsCount.push({word, count: 1, createdAt: placeholderDate});
};

const upsertScrapedWordsCount = async () => {
  try {
    // in order to remove inconsistencies between lesser occurring words,
    // we must overwrite the createdAt date
    const createdAt = new Date();
    createdAt.setMinutes(0, 0, 0);

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
      const {word, count} = wordsCount[i];
      await DailyScrapedWordCount.updateOne(
        {word, createdAt},
        {$inc: {count}},
        {upsert: true}
      );
    }

    const trueAmountWords = wordsCount.reduce(
      (accumulator, currentValue) => accumulator + currentValue.count,
      0
    );
    const hhmmss = new Date().toTimeString().split(' ')[0];

    console.log(
      `[${hhmmss}] Successfully upserted ${wordsCount.length} unique words and ${trueAmountWords} words in total`
    );
  } catch (e) {
    console.log('Failed to upsert scrapedWordsCount', e);
  }
};

// upsert every minute
setInterval(() => upsertScrapedWordsCount(), 1000 * 60);
