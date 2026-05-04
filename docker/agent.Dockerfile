FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        git \
        ripgrep \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/securebench

COPY pyproject.toml README.md ./
COPY securebench ./securebench

RUN python -m pip install --upgrade pip \
    && python -m pip install .

WORKDIR /workspace

CMD ["python", "-m", "securebench.agent.run", "--help"]
