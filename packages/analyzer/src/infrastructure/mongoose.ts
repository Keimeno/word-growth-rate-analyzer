import mongoose from 'mongoose';

const {
  MONGO_INITDB_USERNAME,
  MONGO_INITDB_PASSWORD,
  MONGO_INITDB_DATABASE,
  MONGO_HOST,
  MONGO_PORT,
} = process.env;

mongoose.set('useCreateIndex', true);

export const connection = mongoose.createConnection(
  `mongodb://${MONGO_INITDB_USERNAME}:${MONGO_INITDB_PASSWORD}@${MONGO_HOST}:${MONGO_PORT}/${MONGO_INITDB_DATABASE}`,
  {useNewUrlParser: true, useUnifiedTopology: true, useFindAndModify: false}
);

connection.on('open', () => {
  console.info('Created MongoDB connection.');
});

connection.on('error', err => {
  console.error('Failed to create MongoDB connection');
  console.error(err);
});
