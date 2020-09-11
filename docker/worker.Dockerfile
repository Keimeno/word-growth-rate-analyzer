FROM node:12 as builder
WORKDIR /usr/src/worker/

COPY ./package.json .
COPY ./packages/worker/package.json ./packages/worker/

RUN yarn
RUN cd ./packages/worker && yarn

RUN cd ./packages/worker && yarn compile

COPY . .

CMD ["yarn", "start:worker"]