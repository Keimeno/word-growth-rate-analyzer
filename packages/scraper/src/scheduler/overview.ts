import scheduler from 'node-schedule';
import {notifyMobile} from '@keimeno/wgra-common';
import {OverviewState, overviewState} from '../state';

// the scheduler function call and the formatNumberWithSeparator
// utility function were both generated by github copilot 🤯

// format a number with thousands separator
const formatNumber = (num: number) => {
  const parts = num.toString().split('.');
  parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, '.');
  return parts.join('.');
};

// schedule a job to run every 6 hours
scheduler.scheduleJob('0 */6 * * *', async () => {
  const state: Partial<OverviewState & {[key: string]: string}> = {};
  Object.keys(overviewState).forEach(key => {
    state[key] = formatNumber(overviewState[key]);
  });

  await notifyMobile({
    business: 'WGRA Scraper',
    object: 'Overview',
    body:
      `Processed Words: ${state.totalProcessedWordCount}; ` +
      `Unique Words: ${state.totalProcessedUniqueWordCount}; ` +
      `Successful requests: ${state.successCount}; ` +
      `Unsuccessful requests: ${state.errorCount}`,
  });

  Object.keys(state).forEach(key => {
    overviewState[key] = 0;
  });
});
