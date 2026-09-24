FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY projecthunt ./projecthunt
RUN useradd --system --no-create-home --uid 10001 projecthunt
USER 10001:10001
ENV PYTHONDONTWRITEBYTECODE=1
CMD ["uvicorn","projecthunt.api:app","--host","0.0.0.0","--port","8000"]
