FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY contractguard ./contractguard
RUN pip install --no-cache-dir '.[postgres,server]'
USER 65532:65532
EXPOSE 8080
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--timeout", "60", "--worker-tmp-dir", "/tmp", "contractguard.server:create_app()"]
