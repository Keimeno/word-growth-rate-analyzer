FROM node:12 as builder
WORKDIR /usr/src/scraper/

COPY ./package.json .
COPY ./packages/scraper/package.json ./packages/scraper/

RUN npm i -g pnpm
RUN pnpm i -g tsc-watch
RUN pnpm install

COPY . .

CMD ["pnpm", "start:scraper"]
