FROM python:3.12.16-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Run as an unprivileged user. /data is created here (before VOLUME) so a
# fresh named volume inherits app ownership; a bind mount must be chowned
# to 1000:1000.
RUN useradd --uid 1000 --user-group --create-home app \
    && mkdir -p /data \
    && chown app:app /data

COPY bot ./bot
COPY images ./images

USER app

VOLUME ["/data"]

CMD ["python", "-m", "bot.main"]
