FROM python:3.12-slim
RUN pip install --no-cache-dir pillow
WORKDIR /app
COPY card_render.py tvfeed.py /app/
EXPOSE 8871
CMD ["python", "-u", "/app/tvfeed.py"]
