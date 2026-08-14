FROM python:3.12-slim

WORKDIR /app

# arm64-friendly: everything below installs from prebuilt manylinux/aarch64
# wheels, so no compiler/rust toolchain is required.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY service.py .

EXPOSE 8000

CMD ["bentoml", "serve", "service:ServeDemo", "--host", "0.0.0.0", "--port", "8000"]
