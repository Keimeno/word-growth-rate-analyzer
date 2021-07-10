FROM node:12
WORKDIR /usr/src/scraper/

COPY ./package.json .
COPY ./packages/scraper/package.json ./packages/scraper/
COPY ./packages/common/package.json ./packages/common/

RUN npm i -g pnpm
RUN pnpm i -g tsc-watch
RUN pnpm install

COPY . .

CMD ["pnpm", "start:scraper"]
