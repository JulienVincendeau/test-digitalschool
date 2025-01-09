FROM golang:1.13-alpine as builder
WORKDIR /app
COPY invoke.go ./
RUN CGO_ENABLED=0 GOOS=linux go build -v -o server

FROM python:3.12.3-slim
USER root
RUN apt-get update -y && \
  apt-get install --no-install-recommends -y -q && \
  apt-get clean && \
  apt list --installed && \
  rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

WORKDIR .
COPY --from=builder /app/server ./
COPY script.sh ./
COPY . ./

RUN pip install -r requirements.txt

ENTRYPOINT "./server"