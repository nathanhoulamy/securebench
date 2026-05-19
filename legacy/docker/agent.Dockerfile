ARG PYTHON_VERSION=3.11-slim
FROM python:${PYTHON_VERSION}
ARG ENVIRONMENT_PACKAGES=""

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/opt/securebench-agent

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        git \
        ripgrep \
        ${ENVIRONMENT_PACKAGES} \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/securebench-agent

COPY securebench_agent ./securebench_agent

WORKDIR /workspace

CMD ["python", "-m", "securebench_agent.run", "--help"]
