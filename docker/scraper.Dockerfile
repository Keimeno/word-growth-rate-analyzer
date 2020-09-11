FROM node:12 as builder
WORKDIR /usr/src/scraper/

COPY ./package.json .
COPY ./packages/scraper/package.json ./packages/scraper/

RUN yarn
RUN cd ./packages/scraper && yarn

RUN cd ./packages/scraper && yarn compile

COPY . .

CMD ["yarn", "start:scraper"]