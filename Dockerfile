FROM python:3.11-slim

WORKDIR /srv/exam

# Install dependencies first for better layer caching
COPY app/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY app/ .

# DB_PATH points to the /data volume so SQLite data persists across
# container rebuilds; FLASK_DEBUG=0 disables the dev reloader/debugger.
ENV DB_PATH=/data/database.db \
    FLASK_DEBUG=0 \
    PYTHONUNBUFFERED=1

RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 32220

CMD ["python", "app.py"]
