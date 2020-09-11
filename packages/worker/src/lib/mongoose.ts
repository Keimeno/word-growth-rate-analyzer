import mongoose from 'mongoose';

const {
  MONGO_INITDB_USERNAME,
  MONGO_INITDB_PASSWORD,
  MONGO_INITDB_DATABASE,
  MONGO_HOST,
  MONGO_PORT,
} = process.env;

export const mongoConnection = mongoose.createConnection(
  `mongodb://${MONGO_INITDB_USERNAME}:${MONGO_INITDB_PASSWORD}@${MONGO_HOST}:${MONGO_PORT}/${MONGO_INITDB_DATABASE}`,
  {useNewUrlParser: true, useUnifiedTopology: true, useFindAndModify: false}
);

mongoConnection.on('open', () => {
  console.info('Created MongoDB connection.');
});

mongoConnection.on('error', err => {
  console.error('Failed to create MongoDB connection');
  console.error(err);
});
