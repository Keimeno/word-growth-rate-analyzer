FROM node:12
WORKDIR /usr/src/scraper/

COPY ./package.json .
COPY ./pnpm-workspace.yaml .
COPY ./packages/scraper/package.json ./packages/scraper/
COPY ./packages/common/package.json ./packages/common/

RUN npm i -g pnpm
RUN pnpm install

COPY . .

RUN pnpm build

CMD ["pnpm", "start:scraper"]
