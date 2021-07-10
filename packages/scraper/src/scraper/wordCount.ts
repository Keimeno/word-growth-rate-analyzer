import {CommentStream} from 'snoostorm';
import {Comment} from 'snoowrap';
import {client} from '../infrastructure';
import {incrementScrapedWordCount} from '../publisher';

// every 5 seconds, it gets a maximum of 10000 comments
// because the reddit api ratelimit is 600 api calls every 10 minutes
const comments = new CommentStream(client, {
  subreddit: 'all',
  limit: 10000,
  pollTime: 5000,
});

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

comments.on('item', item => {
  const words = retrieveWords(item);

  words.forEach(incrementScrapedWordCount);
});
