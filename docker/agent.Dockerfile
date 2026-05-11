ARG PYTHON_VERSION=3.11
FROM python:${PYTHON_VERSION}-slim
ARG ENVIRONMENT_PACKAGES=""

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        git \
        ripgrep \
        ${ENVIRONMENT_PACKAGES} \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/securebench

COPY pyproject.toml README.md ./
COPY securebench ./securebench

RUN python -m pip install --upgrade pip \
    && python -m pip install .

WORKDIR /workspace

CMD ["python", "-m", "securebench.agent.run", "--help"]
