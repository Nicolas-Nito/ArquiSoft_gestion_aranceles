FROM python:3.12.7-bookworm

WORKDIR /app

COPY requirements.txt .

RUN pip install wheel setuptools pip --upgrade
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
