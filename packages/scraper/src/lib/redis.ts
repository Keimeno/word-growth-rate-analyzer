import IORedis from 'ioredis';

const {REDIS_HOST, REDIS_PORT, REDIS_PASSWORD} = process.env;

export const redis = new IORedis(+(REDIS_PORT + ''), REDIS_HOST, {
  password: REDIS_PASSWORD,
});
