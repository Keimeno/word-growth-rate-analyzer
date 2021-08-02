import scheduler from 'node-schedule';
import {DailyScrapedWordCount} from '../models';
import {flattenDate, parseNumberArray, parseStringArray} from '../utils';

const {SUBREDDITS, THRESHOLD_LIMITS} = process.env;
const subreddits = parseStringArray(SUBREDDITS);
const thresholdLimits = parseNumberArray(THRESHOLD_LIMITS);

// schedule a job to run at 00:30 every day
scheduler.scheduleJob('0 30 * * *', async () => {
  // delete all entries in the daily-scraped-word-count table
  // that are older than a day
  // and the count is less than the allowed threshold
  for (let i = 0; i < subreddits.length; i++) {
    try {
      await DailyScrapedWordCount.deleteMany({
        createdAt: {
          $ne: flattenDate(new Date()),
        },
        subreddit: subreddits[i],
        count: {
          $lte: thresholdLimits[i],
        },
      });
    } catch (e) {
      console.error(e);
    }
  }
});
