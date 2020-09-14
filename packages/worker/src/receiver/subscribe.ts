import {redis} from '../lib';
import {storeWordsCount} from './process';

export type ScrapedWordCount = {
  word: string;
  count: number;
};

const scrapedWordsCount = 'scrapedWordsCount';

redis.psubscribe(scrapedWordsCount).then(() => {
  console.log(`Subscribed to ${scrapedWordsCount}`);
});

redis.on('pmessage', async (_, __, message) => {
  const scrapedWordsCount = JSON.parse(message) as ScrapedWordCount[];

  console.log(`received ${scrapedWordsCount.length} word counts`);
  await storeWordsCount(scrapedWordsCount);
});
