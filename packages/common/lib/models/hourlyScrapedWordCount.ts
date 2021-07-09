import {Schema, Document, Connection} from 'mongoose';

export type ScrapedWordCount = {
  readonly word: string;
  createdAt: Date;
  count: number;
};

type HourlyScrapedWordCountDocument = Document & ScrapedWordCount;

const hourlyScrapedWordCountSchema = new Schema(
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
    createdAt: {
      type: Date,
    },
  },
  {
    versionKey: false,
    timestamps: false,
  }
);

export const generateHourlyScrapedWordCountModel = (connection: Connection) => {
  return connection.model<HourlyScrapedWordCountDocument>(
    'HourlyScrapedWordCountDocument',
    hourlyScrapedWordCountSchema,
    'hourly_scraped_word_count'
  );
};
