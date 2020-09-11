import {CommentStream} from 'snoostorm';
import {Comment} from 'snoowrap';
import {_} from '../lib';
import {incrementScrapedWordCount} from '../scraped';

// every 2.5 seconds, it gets a maximum of 500 comments
const comments = new CommentStream(_, {
  subreddit: 'all',
  limit: 500,
  pollTime: 5000,
});

const retrieveWords = (item: Comment) => {
  const {body} = item;
  const unprocessedWords = body.split(' ');

  // if we length of the word is longer than 64 we don't accept it
  const filteredWords = unprocessedWords.filter(word => word.length <= 64);

  // only allow words that are alphabetical, and may have apostrophes
  const words = filteredWords.filter(word => /^[a-zA-Z']+$/.test(word));

  // turn all words into lowercase
  return words.map(word => word.toLowerCase());
};

comments.on('item', item => {
  const words = retrieveWords(item);

  words.forEach(incrementScrapedWordCount);
});
