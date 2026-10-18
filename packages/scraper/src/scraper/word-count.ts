import {config} from '@keimeno/wgra-common';
import {Comment} from 'snoowrap';
import {getClient} from '../infrastructure';
import {incrementScrapedWordCount} from '../publisher';
import {CommentStream} from './comment-stream';

// reddit never returns more than 100 items per listing request, a higher
// limit makes snoowrap paginate and burns through the rate limit
const LISTING_LIMIT = 100;

const retrieveWords = (item: Comment) => {
  const {body} = item;

  // urls would otherwise turn into long garbage words
  const text = body.replace(/https?:\/\/\S+/g, ' ').toLowerCase();

  // words are sequences of unicode letters and digits, apostrophes are
  // only kept inside of a word (e.g. "don't", but not "'quoted'")
  const words = text.match(/[\p{L}\p{N}]+(?:'[\p{L}\p{N}]+)*/gu) ?? [];

  // if the length of the word is longer than 64 we don't accept it
  return words.filter(word => word.length <= 64);
};

config.subreddits.forEach(subreddit => {
  const stream = new CommentStream(getClient, {
    subreddit: subreddit.name,
    limit: LISTING_LIMIT,
    pollTime: subreddit.pollFrequency,
  });

  stream.on('item', comment => {
    const words = retrieveWords(comment);

    words.forEach(word => incrementScrapedWordCount(subreddit.name, word));
  });
});
