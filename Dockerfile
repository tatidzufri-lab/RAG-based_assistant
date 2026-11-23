FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Ставим только то, что нужно боту: см. пояснение в requirements-bot.txt
COPY requirements-bot.txt ./
RUN pip install --no-cache-dir -r requirements-bot.txt

COPY run_bot.py ./
COPY assistant_api/ ./assistant_api/
COPY assistant_giga/ ./assistant_giga/
COPY data/ ./data/
COPY data_en/ ./data_en/

# UID должен совпадать с владельцем примонтированных chroma_db и базы логов
# на хосте, иначе бот не сможет записать индекс. На сервере это 1000.
ARG APP_UID=1000
RUN useradd --create-home --uid ${APP_UID} app \
    && mkdir -p /app/assistant_api/chroma_db /app/assistant_giga/chroma_db \
    && chown -R app:app /app
USER app

CMD ["python", "run_bot.py"]
