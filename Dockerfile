# API image: builds the C++ aggregation/cascade library and serves the FastAPI app.
# The web client is NOT in this image; it is deployed to Cloudflare Workers.
FROM python:3.12-slim AS native
RUN apt-get update && apt-get install -y --no-install-recommends build-essential cmake && rm -rf /var/lib/apt/lists/*
COPY native /src/native
RUN cmake -S /src/native -B /src/native/build -DCMAKE_BUILD_TYPE=Release \
 && cmake --build /src/native/build && /src/native/build/solagg_test && /src/native/build/cascade_test

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY api/requirements.txt api/requirements.txt
RUN pip install -r api/requirements.txt
COPY api api
COPY --from=native /src/native/build/libsolagg.so native/build/libsolagg.so
# Pre-train the churn model so the first request is fast.
RUN python -m api.ml.train --wallets 6000 >/dev/null
EXPOSE 8787
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/api/health')"
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8787", "--workers", "2"]
