FROM php:8.2-cli

WORKDIR /app

COPY . .

# install dependencies
RUN apt-get update \
 && apt-get install -y curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# make script executable
RUN chmod +x start.sh

CMD ["bash", "start.sh"]