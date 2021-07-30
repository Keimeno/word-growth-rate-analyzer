export const flattenDate = (date: Date) => {
  date.setMinutes(0, 0, 0);
  date.setHours(0);
  return date;
};
