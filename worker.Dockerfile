FROM node:12 as builder
WORKDIR /usr/src/worker/

COPY ./package.json .
COPY ./packages/worker/package.json ./packages/worker/

RUN npm i -g pnpm
RUN pnpm i -g tsc-watch
RUN pnpm install

COPY . .

CMD ["pnpm", "start:worker"]
