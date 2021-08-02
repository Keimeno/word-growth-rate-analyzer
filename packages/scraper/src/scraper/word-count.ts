import {Comment} from 'snoowrap';
import {client} from '../infrastructure';
import {incrementScrapedWordCount} from '../publisher';
import {parseNumberArray, parseStringArray} from '../utils';
import {CommentStream} from './comment-stream';

const {SUBREDDITS, POLL_TIMES} = process.env;

const subreddits = parseStringArray(SUBREDDITS);
const pollTimes = parseNumberArray(POLL_TIMES);

const retrieveWords = (item: Comment) => {
  const {body} = item;
  const unprocessedWords = body.split(' ');

  // if the length of the word is longer than 64 we don't accept it
  const filteredWords = unprocessedWords
    .map(word => word.replace(/[^\w\s]/gi, ''))
    .filter(word => word.length <= 64);

  // only allow words that are alphabetical, and may have apostrophes
  const words = filteredWords.filter(word => /^[a-zA-Z0-9']+$/.test(word));

  // turn all words into lowercase
  return words.map(word => word.toLowerCase());
};

subreddits.forEach((subreddit, index) => {
  const stream = new CommentStream(client, {
    subreddit,
    limit: 100000,
    pollTime: pollTimes[index],
  });

  stream.on('item', comment => {
    const words = retrieveWords(comment);

    words.forEach(word => incrementScrapedWordCount(subreddit, word));
  });
});
