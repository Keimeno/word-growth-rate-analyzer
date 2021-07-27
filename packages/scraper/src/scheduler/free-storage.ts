import scheduler from 'node-schedule';
import {DailyScrapedWordCount} from '../models';
import {flattenDate} from '../utils';

// schedule a job to run at 00:30 every day
scheduler.scheduleJob('0 30 * * *', async () => {
  // delete all entries in the daily-scraped-word-count table
  // that are older than a day
  // and the count is less than 11
  try {
    await DailyScrapedWordCount.deleteMany({
      createdAt: {
        $lt: flattenDate(new Date(Date.now() - 24 * 60 * 60 * 1000)),
      },
      count: {
        $lte: 10,
      },
    });
  } catch (e) {
    console.error(e);
  }
});
