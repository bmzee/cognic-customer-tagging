# The reader's image: the read-only MCP tool server, its code, the taxonomy
# and a read-only synthetic fixture store. Built in CI only
# (.github/workflows/image.yml); never on a shared machine.
#
# No package is installed, at build time or at run time. The base image is
# pinned by digest (python:3.12-slim, the multi-architecture index digest
# looked up with Docker Hub's API on 2026-10-18).
#
# Run it with no network and a read-only root:
#   docker run --rm -i --network none --read-only --cap-drop ALL \
#     --security-opt no-new-privileges customer-tagging-profiles
# In production the bank's store is mounted read-only at /data/profile.db,
# replacing the fixture (docs/OPEN-QUESTIONS.md, Q29).

ARG BASE=python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1

# Stage 1: compile the synthetic fixture store from the repository's data.
FROM ${BASE} AS fixture
ARG SOURCE_DATE_EPOCH=1788220800
ENV PYTHONDONTWRITEBYTECODE=1 SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH}
WORKDIR /build
COPY engine/ engine/
COPY taxonomy/ taxonomy/
COPY data/customers.csv data/transactions.csv data/
RUN python3 -m engine.build --rebuild --customers data/customers.csv \
        --transactions data/transactions.csv --store /build/profile.db

# Stage 2: the reader.
FROM ${BASE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY --chmod=0555 bin/profile-reader /app/profile-reader
COPY --chmod=0444 engine/ /app/engine/
COPY --chmod=0444 server/ /app/server/
COPY --chmod=0444 taxonomy/ /app/taxonomy/
COPY --from=fixture --chmod=0444 /build/profile.db /data/profile.db
RUN chmod 0555 /app /app/engine /app/engine/migrations /app/server /app/taxonomy /data
USER 10001:10001
WORKDIR /app
ENTRYPOINT ["/app/profile-reader"]
CMD ["--store", "/data/profile.db"]
