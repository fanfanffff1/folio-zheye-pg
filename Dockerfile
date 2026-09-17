FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /app/catalog /app/data/uploads/avatars /app/data/uploads/submissions \
    && cp /app/data/cleaned-books.json /app/catalog/ \
    && if [ -f /app/data/enrichment.json ]; then cp /app/data/enrichment.json /app/catalog/; fi \
    && chmod +x entrypoint.sh
ENV FOLIO_DATA_DIR=/app/data
ENV FOLIO_CATALOG_DIR=/app/catalog
ENV PORT=8000
EXPOSE 8000
CMD ["./entrypoint.sh"]
