import {Schema, Document, Connection} from 'mongoose';

export type ScrapedWordCount = {
  readonly word: string;
  readonly subreddit: string;
  createdAt: Date;
  count: number;
};

type DailyScrapedWordCountDocument = Document & ScrapedWordCount;

const dailyScrapedWordCountSchema = new Schema<DailyScrapedWordCountDocument>(
  {
    word: {
      type: String,
      index: true,
    },
    subreddit: {
      type: String,
      index: true,
    },
    createdAt: {
      type: Date,
      index: true,
    },
    count: {
      type: Number,
      default: 1,
    },
  },
  {
    versionKey: false,
    timestamps: false,
  }
);

// every upsert and every analyzer lookup filters by these three fields
dailyScrapedWordCountSchema.index({subreddit: 1, word: 1, createdAt: 1});

export const generateDailyScrapedWordCountModel = (connection: Connection) => {
  return connection.model<DailyScrapedWordCountDocument>(
    'DailyScrapedWordCountDocument',
    dailyScrapedWordCountSchema,
    'daily_scraped_word_count'
  );
};
