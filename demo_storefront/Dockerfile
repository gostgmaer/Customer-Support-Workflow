FROM python:3.12-slim

WORKDIR /srv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . ./demo_storefront

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "demo_storefront.main:app", "--host", "0.0.0.0", "--port", "8000"]
