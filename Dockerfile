FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    curl \
    wget \
    git \
    pigz \
    fastp \
    salmon \
    pandoc \
    r-base \
    r-base-dev \
    libcurl4-openssl-dev \
    libssl-dev \
    libxml2-dev \
    libharfbuzz-dev \
    libfribidi-dev \
    libfreetype6-dev \
    libpng-dev \
    libtiff5-dev \
    libjpeg-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir snakemake typer pyyaml

RUN Rscript -e "options(repos='https://cloud.r-project.org'); install.packages(c('data.table','readr','dplyr','ggplot2','rmarkdown','jsonlite'))"
RUN Rscript -e "options(repos='https://cloud.r-project.org'); if (!requireNamespace('BiocManager', quietly=TRUE)) install.packages('BiocManager'); BiocManager::install(c('tximport','DESeq2','apeglm','EnhancedVolcano'), ask=FALSE, update=FALSE)"

COPY . /app

CMD ["python", "-m", "app", "run", "--help"]
