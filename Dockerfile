FROM node:latest AS build

RUN mkdir /frontend

COPY ./frontend/index.html /frontend/index.html
COPY ./frontend/package.json /frontend/package.json
COPY ./frontend/vite.config.js /frontend/vite.config.js
COPY ./frontend/src /frontend/src
COPY ./frontend/public /frontend/public

WORKDIR /frontend
RUN yarn install && yarn build

FROM python:3.11-bullseye
ENV PYTHONBUFFERED=1

RUN apt-get update && apt-get upgrade -y && apt-get install -y \
  cifs-utils

RUN mkdir /backend
WORKDIR /backend
COPY ./backend/pyproject.toml /backend/pyproject.toml

RUN \
  pip install -U pip && \
  pip install poetry && \
  poetry config virtualenvs.create false && \
  poetry install --no-interaction --no-ansi

COPY ./backend /backend
COPY --from=build /frontend/dist/ /frontend

ADD ./mlt .mlt
RUN apt update && apt -y install cmake build-essential
RUN cd mlt && cmake . && cmake --build . && cmake --install .

CMD ["./manage", "start"]
