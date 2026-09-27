FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir pandas numpy requests
COPY robo.py agendador.py painel.py sombra.py /app/
ENV PASTA_ESTADO=/app/estado
VOLUME ["/app/estado"]
EXPOSE 3000
CMD ["python", "/app/agendador.py"]
