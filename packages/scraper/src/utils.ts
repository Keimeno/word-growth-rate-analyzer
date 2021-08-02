export const flattenDate = (date: Date) => {
  date.setMinutes(0, 0, 0);
  date.setHours(0);
  return date;
};

/**
 * for parsing arrays set in env variables
 */
export const parseStringArray = (input?: string) => (input ?? '').split(',');

/**
 * for parsing number arrays set in env variables
 */
export const parseNumberArray = (input?: string) =>
  parseStringArray(input).map(x => parseInt(x));
