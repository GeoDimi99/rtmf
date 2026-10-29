# Single-stage Dockerfile for deploy-manager

FROM python:3.14-slim

# Environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Working directory
WORKDIR /app

# Runtime dependencies (Git needed by GitPython)
RUN apt-get update && \
    apt-get install -y --no-install-recommends git && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy source code
COPY tooling/legacy/orchestration-grpc/deploy-manager/pyproject.toml .
COPY tooling/legacy/orchestration-grpc/deploy-manager/src/ ./src/
COPY runtime/orchestration/task-wrapper/grpc/ ./task-wrapper/
COPY runtime/common/shared/include/ task-wrapper/include/
COPY runtime/common/orchestration-grpc/include/ task-wrapper/include/
COPY runtime/common/shared/src/ task-wrapper/src/
COPY runtime/common/orchestration-grpc/src/ task-wrapper/src/

# Copy task manifest
COPY tests/tasks/orchestration-grpc/ ./tests/test_0_code/


# Install deploy-manager and its dependencies
RUN pip install --no-cache-dir .

# Entrypoint
ENTRYPOINT ["python", "-m", "src.main"]