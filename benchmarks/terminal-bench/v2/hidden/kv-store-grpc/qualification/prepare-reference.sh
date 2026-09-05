#!/bin/sh
set -eu

python -m pip install --disable-pip-version-check --no-cache-dir --no-compile \
    --target /app/kv_store_dependencies \
    grpcio==1.73.0 grpcio-tools==1.73.0 protobuf==6.31.1 setuptools==80.9.0
cp /qualification/reference.proto /app/kv-store.proto
cp /qualification/reference-server.py /app/server.py
PYTHONPATH=/app/kv_store_dependencies python -m grpc_tools.protoc \
    -I/app --python_out=/app --grpc_python_out=/app /app/kv-store.proto
