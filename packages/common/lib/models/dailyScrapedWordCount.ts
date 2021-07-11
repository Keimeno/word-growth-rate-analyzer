import {Schema, Document, Connection} from 'mongoose';

export type ScrapedWordCount = {
  readonly word: string;
  createdAt: Date;
  count: number;
};

type DailyScrapedWordCountDocument = Document & ScrapedWordCount;

const dailyScrapedWordCountSchema = new Schema(
  {
    word: {
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

export const generateDailyScrapedWordCountModel = (connection: Connection) => {
  return connection.model<DailyScrapedWordCountDocument>(
    'DailyScrapedWordCountDocument',
    dailyScrapedWordCountSchema,
    'daily_scraped_word_count'
  );
};
