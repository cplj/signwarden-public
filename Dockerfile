FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# curl is used only for explicit local API checks, never by the service itself.
RUN apt-get update && apt-get install -y --no-install-recommends curl

# Copy only public product inputs; do not copy credentials or the whole context.
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY signwarden/ ./signwarden/
COPY examples/reference_gateway.py ./examples/reference_gateway.py
COPY cases/sample.json ./cases/sample.json
COPY docs/case-format.md ./docs/case-format.md
COPY tests/test_product.py ./tests/test_product.py

RUN python -m pip install --no-cache-dir . \
    && mkdir /reports \
    && chown 65532:65532 /reports

USER 65532:65532

ENTRYPOINT ["signwarden"]
CMD ["serve", "--adapter", "examples/reference_gateway.py:Adapter", "--port", "8765"]
