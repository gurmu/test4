FROM python:3.11-slim

WORKDIR /app

COPY src/api/nice_incontact/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/api/nice_incontact/ .

EXPOSE 8001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
