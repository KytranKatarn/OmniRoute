FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir flask requests PyJWT werkzeug
COPY app.py auth.py kytran_auth.py ./
EXPOSE 8080
CMD ["python", "app.py"]
