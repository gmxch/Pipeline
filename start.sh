#!/bin/bash

SPACE_URL="https://gmxch-ltcfarn.hf.space"

echo "Starting HTTP server..."

php -S 0.0.0.0:7860 server.php &

echo "Starting workers..."

for host in 1 2
do
  for worker in 1 2 3 4 5
  do
    echo "Starting bot worker=$worker host=$host"
    php bot.php $worker $host &
  done
done

echo "Workers started."

echo "Starting keep-alive ping loop..."

while true
do
  curl -s \
  -H "Authorization: Bearer $HF_TOKEN" \
  "$SPACE_URL/ping" > /dev/null

  sleep 120
done