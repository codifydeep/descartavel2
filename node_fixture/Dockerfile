FROM node@sha256:b6f26b36c8ff49624cfdac716b8ea1138d606df02586a77d364bb5536a634f85
ARG SOURCE_SHA
ENV SOURCE_SHA=${SOURCE_SHA}
LABEL delivery-kit.source-sha="${SOURCE_SHA}"
WORKDIR /app
COPY node_fixture/score.js node_fixture/server.js ./
USER 10000:10000
EXPOSE 8080
CMD ["node", "server.js"]
