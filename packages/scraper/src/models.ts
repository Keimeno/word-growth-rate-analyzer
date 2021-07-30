import {generateDailyScrapedWordCountModel} from '@keimeno/wgra-common';
import {connection} from './infrastructure';

export const DailyScrapedWordCount =
  generateDailyScrapedWordCountModel(connection);
DailyScrapedWordCount.init();
