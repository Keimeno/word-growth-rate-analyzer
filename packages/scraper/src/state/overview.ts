export interface OverviewState {
  errorCount: number;
  successCount: number;
  totalProcessedWordCount: number;
  totalProcessedUniqueWordCount: number;
}

export const overviewState: OverviewState & {[key: string]: number} = {
  errorCount: 0,
  successCount: 0,
  totalProcessedWordCount: 0,
  totalProcessedUniqueWordCount: 0,
};
