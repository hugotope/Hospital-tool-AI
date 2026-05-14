FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV HOSPITAL_CORS_ORIGINS=http://localhost,http://127.0.0.1

COPY back-end/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

COPY . /app
RUN mkdir -p /app/uploaded_datasets

ENV HOSPITAL_HOST=0.0.0.0
ENV HOSPITAL_PORT=8000

EXPOSE 8000

CMD ["python", "back-end/app.py"]
