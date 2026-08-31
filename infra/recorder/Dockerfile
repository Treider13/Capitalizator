FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md /app/
COPY src /app/src
RUN pip install --no-cache-dir -e .
# Recorder image has no API keys and does not copy signer secrets.
EXPOSE 8081
CMD ["python", "-m", "capitalizator.recorder.app", "--serve", "--host", "0.0.0.0", "--port", "8081"]
