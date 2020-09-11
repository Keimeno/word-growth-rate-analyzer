FROM node:12 as builder
WORKDIR /usr/src/scraper/

COPY ./package.json .
COPY ./packages/scraper/package.json ./packages/scraper/

RUN yarn
RUN cd ./packages/scraper && yarn

COPY . .

CMD ["yarn", "start:scraper"]