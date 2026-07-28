# Base image pinned to python:3.11-slim for reproducible rebuilds.
FROM python:3.11-slim@sha256:d0d43a8b0c352c215cd1381f3f4d7ac34cf3440cd0415873451d7affca53a769

ENV DEBIAN_FRONTEND=noninteractive

ARG DEBIAN_SNAPSHOT=20260727T000000Z
ARG SALMON_VERSION=1.10.0
ARG SALMON_SHA256=b876d041ef3bfbe44422b052b99ce387ff4e521c76002355c7b27882cf19c01b
ARG SALMON_SOURCE_SHA256=fd8039c20f8dc717d414c89d32ce80a37b1cf4fda2eb9dba839adedd33a4fa3a
ARG FASTP_VERSION=0.23.4
ARG FASTP_SHA256=4037508afcfa41e85586d4f06bb001bb73d9f29f159fb264c59b98deff27d377
ARG CRAN_SNAPSHOT=2026-02-02
ARG BIOC_VERSION=3.21

ENV SALMON_VERSION=${SALMON_VERSION} \
    SALMON_SHA256=${SALMON_SHA256} \
    SALMON_SOURCE_SHA256=${SALMON_SOURCE_SHA256} \
    FASTP_VERSION=${FASTP_VERSION} \
    FASTP_SHA256=${FASTP_SHA256} \
    CRAN_REPO=https://packagemanager.posit.co/cran/${CRAN_SNAPSHOT} \
    BIOC_VERSION=${BIOC_VERSION}

WORKDIR /app

RUN set -eux; \
    rm -f /etc/apt/sources.list.d/debian.sources; \
    printf '%s\n' \
      "deb [check-valid-until=no signed-by=/usr/share/keyrings/debian-archive-keyring.pgp] http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT} trixie main" \
      "deb [check-valid-until=no signed-by=/usr/share/keyrings/debian-archive-keyring.pgp] http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT} trixie-updates main" \
      "deb [check-valid-until=no signed-by=/usr/share/keyrings/debian-archive-keyring.pgp] http://snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT} trixie-security main" \
      > /etc/apt/sources.list; \
    apt-get -o Acquire::Check-Valid-Until=false update; \
    apt-get -y upgrade; \
    apt-get install -y --no-install-recommends \
      build-essential=12.12 \
      ca-certificates=20250419 \
      curl=8.14.1-2+deb13u4 \
      wget=1.25.0-2 \
      git=1:2.47.3-0+deb13u1 \
      pigz=2.8-1 \
      pandoc=3.1.11.1+ds-2 \
      r-base=4.5.0-3 \
      r-base-dev=4.5.0-3 \
      libcurl4-openssl-dev=8.14.1-2+deb13u4 \
      libssl-dev=3.5.6-1~deb13u2 \
      libxml2-dev=2.12.7+dfsg+really2.9.14-2.1+deb13u3 \
      libharfbuzz-dev=10.2.0-1+deb13u1 \
      libfontconfig1-dev=2.15.0-2.3 \
      pkg-config=1.8.1-4 \
      libfribidi-dev=1.0.16-1 \
      libfreetype-dev=2.13.3+dfsg-1+deb13u1 \
      libpng-dev=1.6.48-1+deb13u5 \
      libtiff5-dev=4.7.0-3+deb13u3 \
      libjpeg-dev=1:2.1.5-4; \
    rm -rf /var/lib/apt/lists/*

COPY requirements.lock.txt /app/requirements.lock.txt
RUN python -m pip install --no-cache-dir --require-hashes -r /app/requirements.lock.txt

COPY scripts/install_tools.sh /app/scripts/install_tools.sh
RUN chmod +x /app/scripts/install_tools.sh && /app/scripts/install_tools.sh

RUN Rscript -e "options(repos = c(CRAN = Sys.getenv('CRAN_REPO'))); install.packages(c('BiocManager','data.table','readr','dplyr','ggplot2','rmarkdown','jsonlite','yaml'))"
RUN Rscript -e "options(repos = c(CRAN = Sys.getenv('CRAN_REPO'))); BiocManager::install(version = Sys.getenv('BIOC_VERSION'), ask = FALSE, update = FALSE)"
RUN Rscript -e "options(repos = c(CRAN = Sys.getenv('CRAN_REPO'))); BiocManager::install(c('tximport','DESeq2','apeglm','EnhancedVolcano','clusterProfiler','fgsea','AnnotationDbi','GO.db','org.Hs.eg.db','org.Mm.eg.db','org.Rn.eg.db'), ask = FALSE, update = FALSE)"
RUN Rscript -e "pkgs <- c('BiocManager','data.table','readr','dplyr','ggplot2','rmarkdown','jsonlite','yaml','tximport','DESeq2','apeglm','EnhancedVolcano','clusterProfiler','fgsea','AnnotationDbi','GO.db','org.Hs.eg.db','org.Mm.eg.db','org.Rn.eg.db'); missing <- pkgs[!vapply(pkgs, requireNamespace, logical(1), quietly = TRUE)]; if (length(missing)) stop('Missing required R packages: ', paste(missing, collapse = ', '))"

RUN python --version \
 && python -m snakemake --version \
 && salmon --version \
 && fastp --version \
 && R --version

COPY . /app

RUN set -eux; \
    license_dir=/usr/share/licenses/harako-rnaseq; \
    install -d "$license_dir/third-party"; \
    install -m 0644 LICENSE "$license_dir/LICENSE"; \
    install -m 0644 COMMERCIAL_LICENSE.md "$license_dir/COMMERCIAL_LICENSE.md"; \
    install -m 0644 THIRD_PARTY_NOTICES.md "$license_dir/THIRD_PARTY_NOTICES.md"; \
    install -m 0644 CITATION.cff "$license_dir/CITATION.cff"; \
    install -m 0644 docs/provenance.md "$license_dir/provenance.md"; \
    install -m 0644 third_party_licenses/fastp-LICENSE "$license_dir/third-party/fastp-LICENSE"; \
    install -m 0644 third_party_licenses/Salmon-SOURCE.md "$license_dir/third-party/Salmon-SOURCE.md"; \
    install -m 0644 /usr/share/common-licenses/GPL-3 "$license_dir/third-party/Salmon-GPL-3.0"

RUN set -eux; \
    apt-mark manual \
      ca-certificates curl git pigz wget pandoc r-base \
      libcurl4t64 libssl3t64 libxml2 libharfbuzz0b libfontconfig1 \
      libfribidi0 libfreetype6 libpng16-16t64 libtiff6 libjpeg62-turbo; \
    apt-get purge -y --auto-remove \
      build-essential r-base-dev \
      libcurl4-openssl-dev libssl-dev libxml2-dev libharfbuzz-dev \
      libfontconfig1-dev pkg-config libfribidi-dev libfreetype-dev \
      libpng-dev libtiff5-dev libjpeg-dev; \
    rm -rf /var/lib/apt/lists/* /root/.cache

ARG VERSION=dev
ARG REVISION=unknown
ARG CREATED=unknown
ARG SOURCE_URL=https://github.com/do-shima/harako-rnaseq

LABEL org.opencontainers.image.title="Harako-RNAseq" \
      org.opencontainers.image.description="Source-available local bulk RNA-seq analysis application" \
      org.opencontainers.image.source="${SOURCE_URL}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.created="${CREATED}" \
      org.opencontainers.image.documentation="${SOURCE_URL}/blob/${REVISION}/docs/container-image.md" \
      io.harako-rnaseq.source-license="PolyForm-Noncommercial-1.0.0 applies to Harako-RNAseq source only" \
      io.harako-rnaseq.third-party-notices="/usr/share/licenses/harako-rnaseq/THIRD_PARTY_NOTICES.md"

CMD ["python", "-m", "app", "run", "--help"]
