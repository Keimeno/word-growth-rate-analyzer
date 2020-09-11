import {DailyScrapedWordCount, updateDailyScrapedWordModel} from '../models';
import {ScrapedWordCount} from './subscribe';

export const storeWordsCount = async (wordsCount: ScrapedWordCount[]) => {
  await updateDailyScrapedWordModel();

  try {
    for (let i = 0; i < wordsCount.length; i++) {
      const {word, count} = wordsCount[i];
      await DailyScrapedWordCount.updateOne(
        {word},
        {$inc: {count}},
        {upsert: true}
      );
    }
  } catch (e) {
    console.log(e);
  }
};
