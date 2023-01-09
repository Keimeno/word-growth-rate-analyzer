import fs from 'fs';
import path from 'path';

interface Subreddit {
  /**
   * The name of the subreddit, without the leading 'r/'.
   */
  name: string;

  /**
   * A baseline word, that doesn't grow in unsage,
   * and is directly related to the user activity of
   * the subreddit. For an english speaking subreddit,
   * this would be the word 'the'. The most occuring
   * word should be used as a baseline.
   */
  baseline: string;

  /**
   * The frequency at which comments are pulled
   * from a subreddit in milliseconds.
   */
  pollFrequency: number;

  /**
   * Since storing every occuring word would require
   * too much storage space, we have a set threshold,
   * that varies, depending on the subreddit.
   * A scheduled job will run once per day, that will
   * delete all words, that have a count lower than
   * the threshold.
   */
  threshold: number;
}

interface Config {
  subreddits: Subreddit[];
}

export const config: Config = JSON.parse(
  fs.readFileSync(path.join(__dirname, '..', '..', '..', 'config.json'), 'utf8')
);
