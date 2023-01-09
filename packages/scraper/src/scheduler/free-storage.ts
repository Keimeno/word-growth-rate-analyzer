import {config, flattenDate} from '@keimeno/wgra-common';
import scheduler from 'node-schedule';
import {DailyScrapedWordCount} from '../models';

// schedule a job to run at 00:30 every day
scheduler.scheduleJob('30 0 * * *', async () => {
  // delete all entries in the daily-scraped-word-count table
  // that are older than a day
  // and the count is less than the allowed threshold
  await Promise.all(
    config.subreddits.map(async subreddit => {
      try {
        await DailyScrapedWordCount.deleteMany({
          createdAt: {
            $ne: flattenDate(new Date()),
          },
          subreddit: subreddit.name,
          count: {
            $lte: subreddit.threshold,
          },
        });
      } catch (e) {
        console.error(e);
      }
    })
  );
});
