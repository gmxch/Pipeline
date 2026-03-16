<?php

$uri = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);

if ($uri === '/ping') {
    header("Content-Type: text/plain");
    echo "alive ".time();
    exit;
}

echo "ok";