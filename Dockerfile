FROM python:3.11-slim

WORKDIR /app

# Keep image single-stage and minimal.
RUN pip install --no-cache-dir snakemake

COPY . /app

CMD ["python", "-m", "app", "run", "--help"]