# rtmod: the deploy-manager, one image for every implementation.
# Build context: the repository root. Only tooling/dsl and tooling/deploy-manager
# go into the image; the device never receives the builder.
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY tooling/deploy-manager/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY tooling/dsl/ /app/dsl/
COPY tooling/deploy-manager/ /app/deploy-manager/

# Set by install.sh, so 'rtmod --version' and the applied state name the RTMO that ran.
ARG RTMO_VERSION=unknown
ARG RTMO_COMMIT=
ENV RTMO_VERSION=${RTMO_VERSION} \
    RTMO_COMMIT=${RTMO_COMMIT}

ENTRYPOINT ["python", "/app/deploy-manager/main.py"]
