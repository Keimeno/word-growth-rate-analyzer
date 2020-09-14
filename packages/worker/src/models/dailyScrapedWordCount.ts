import {connection} from '../lib/mongoose';
import {Schema, Document, Model} from 'mongoose';
import {ScrapedWordCount} from '../receiver';

type DailyScrapedWordCountDocument = Document & ScrapedWordCount;

const userSchema = new Schema(
  {
    word: {
      type: String,
      unique: true,
      index: true,
    },
    count: {
      type: Number,
      default: 1,
    },
  },
  {
    versionKey: false,
  }
);

const generateDatePrefix = () => {
  const date = new Date();
  return `${date.getFullYear()}-${
    date.getMonth() + 1
  }-${date.getMilliseconds()}`;
};

export let DailyScrapedWordCount: Model<DailyScrapedWordCountDocument, {}>;

export const updateDailyScrapedWordModel = async () => {
  const collectionName = generateDatePrefix() + '_daily_scraped_word_count';

  if (DailyScrapedWordCount?.collection?.name === collectionName) {
    return;
  }

  DailyScrapedWordCount = connection.model<DailyScrapedWordCountDocument>(
    'DailyScrapedWordCountDocument',
    userSchema,
    collectionName
  );

  console.log(
    `DailyScrapedWordCount receives new collection name: ${collectionName}`
  );

  await DailyScrapedWordCount.init();
};

updateDailyScrapedWordModel();
