const scrapedWordsCount = [] as ScrapedWordCount[];

export type ScrapedWordCount = {
  readonly word: string;
  count: number;
};

export const incrementScrapedWordCount = (word: string) => {
  // check if there's already a ScrapedWordCount object in the
  // scraped words count array
  const index = scrapedWordsCount.findIndex(
    wordCount => wordCount.word === word
  );

  // item found, increment
  if (index !== -1) {
    scrapedWordsCount[index].count++;
    return;
  }

  // item not found, create new object with count 1
  scrapedWordsCount.push({word, count: 1});
};

const publishScrapedWordsCount = async () => {
  try {
    console.log(
      `Successfully published the count of ${scrapedWordsCount.length} words`
    );

    // empty scraped words count
    scrapedWordsCount.length = 0;
  } catch (e) {
    console.log(e);
    console.log('Failed to publish scrapedWordsCount, retrying...');
    setTimeout(() => publishScrapedWordsCount(), 5000);
  }
};

// publishing every minute
setInterval(() => publishScrapedWordsCount(), 1000 * 60);
