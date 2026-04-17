FROM python:3.10-alpine

WORKDIR /app

RUN pip install --no-cache-dir lxml requests bs4 charset_normalizer

COPY app.py .

VOLUME ["/app/config"]

ENTRYPOINT ["python", "app.py"]
CMD []
