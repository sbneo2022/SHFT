FROM python:3.7-slim

WORKDIR /app

# prevent apt-get install from prompting on certain packages
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get -y install \
    nginx gcc iputils-ping \
    && rm -rf /var/lib/apt/lists/*

ADD requirements.txt .

RUN pip install --upgrade pip setuptools
RUN pip install -r requirements.txt

RUN mkdir -p bhft
COPY . bhft/

ENV PYTHONPATH="$PYTHONPATH:/app/bhft"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONIOENCODING=UTF-8

WORKDIR /app/bhft
ENTRYPOINT ["python", "service.py"]
