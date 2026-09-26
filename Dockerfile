FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir pandas numpy requests
COPY robo.py agendador.py /app/
ENV PASTA_ESTADO=/app/estado
VOLUME ["/app/estado"]
CMD ["python", "/app/agendador.py"]
