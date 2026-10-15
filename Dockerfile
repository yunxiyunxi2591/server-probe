FROM python:3.12-slim

WORKDIR /app
COPY server.py /app/server.py

ENV PROBE_PORT=25777
EXPOSE 25777

CMD ["python", "-u", "/app/server.py"]
