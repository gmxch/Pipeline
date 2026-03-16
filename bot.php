<?php
ob_implicit_flush(true);
$worker = $argv[1] ?? 1;
$hostIndex = $argv[2] ?? 1;

sleep(rand(5,25));

include_once(__DIR__ . '/loader.php');

$userAgent = 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Mobile Safari/537.36';

$hosts = [
    1 => 'https://litecoinfarm.online',
    2 => 'https://claimfreelitecoin.pp.ua'
];

$host = $hosts[$hostIndex];
$domain = parse_url($host, PHP_URL_HOST);
$reff = '/index.php?ref=413930';


$emails = file(__DIR__."/emails/$worker.txt", FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
$proxies = file(__DIR__."/$hostIndex/$worker.txt", FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);


$cookieFile = __DIR__."/cookie_{$hostIndex}_{$worker}.txt";



$proxyIndex = 0;
$emailIndex = 0;

$totalProxy = count($proxies);
$totalemail = count($emails);

login:
while (true) {
    $mail = $emails[$emailIndex];
    $withdraw = false;
    $new_csrf = null;
    $bal = 0;
    $clk = 0;
    $cookieFile = __DIR__."/cookie_{$hostIndex}_{$worker}.txt";
    @unlink($cookieFile);

    $waitMap = _loadW();
    if (isset($waitMap[$mail]) && time() < $waitMap[$mail]) {
        logx('info', "$mail still waiting");
        goto next_account;
    }

    $proxy = $proxies[$proxyIndex];
    _sProxy($proxy);

    $login_ok = false;
    do {
        $_0 = Net::C($host.$reff, 'GET', null, $cookieFile, [], $host.$reff, $userAgent);
        if (!$_0) {
            logx('warn', 'login GET fail');
            sleep(2);
            continue;
        }

        $f = xScraper::payload($_0)[0];
        $pa = $f['payload'];

        $c = capt::cha($_0);
        $key = $c['keys'][0];
        while (($t = _tK($host, $key)) === false) {
            sleep(2);
        }

        $po = array_merge($pa, [
            'faucet_email' => $mail,
            'cf-turnstile-response' => $t
        ]);
        $_1 = Net::C($host.$reff, 'POST', $po, $cookieFile, [], $host.$reff, $userAgent);
        if (!$_1) continue;

        $balNode = xScraper::xPath($_1, "//span[@id='balance']");
        $clkNode = xScraper::xPath($_1, "//span[@id='clicks_today']");

        if (!empty($balNode) && !empty($clkNode)) {
            preg_match('/[\d\.]+/', $balNode[0], $m);
            $bal = $m[0];
            $login_ok = true;
        }

        if (str_contains($_1, 'only have 1 account')) {
            logx('warn', "$mail blocked → change proxy");
            $proxy = _nProxy($proxyIndex, $proxies);
            _sProxy($proxy);
            @unlink($cookieFile);
        }
    } while(!$login_ok);
    logx('ok', "[".date("H:i:s")."] $mail::logged in");

    $_t = json_decode(Net::X("$host/mine.php", "POST", ["check_timer" => 1], $cookieFile, [], $host, $userAgent), true);

    if (!$_t) {
        logx('warn', "timer fail");
        goto next_account;
    }

    $clk = $_t['clicks_today'];
    $sle = 1;

    $_1 = Net::C("$host/mine.php", 'GET', null, $cookieFile, [], $host."/dashboard.php", $userAgent);
    if (!$_1) {
        logx('warn', "mine page fail");
        goto next_account;
    }

    $c = capt::cha($_1);
    $key = $c['keys'][0];

    do {
        logx('info', "[".date("H:i:s")."] $bal::$clk");

        $start = microtime(true);
        while(($t = _tK($host, $key))===false);
        $solveTime = microtime(true) - $start;

        $_csrf = rScraper::jPath($_1, "/csrfToken\s*=\s*'([^']+)'/");
        $csrf = $new_csrf ?? $_csrf[1][0];
        $_time = (int)(microtime(true) * 1000);
        $_rand = substr(str_shuffle('abcdefghijklmnopqrstuvwxyz0123456789'),0,9);

        $po = [
            "mine_action" => 1,
            "cf-turnstile-response" => $t,
            "request_id" => "CLAIM_{$_time}_{$_rand}",
            "csrf_token" => $csrf
        ];

        $cla = json_decode(Net::X("$host/mine.php", "POST", $po, $cookieFile, [], $host, $userAgent), true);
        if (!$cla) {
            logx('warn', "mine request fail");
            goto next_account;
        }

        if (!empty($cla['success'])) {
            $new_csrf = $cla['new_csrf_token'];
            $bal = $cla['new_balance'];
            $clk = $cla['total_clicks'];
            $sle = $cla['remaining_time'];
        }

        if (isset($cla['message']) && str_contains($cla['message'], 'Invalid CSRF')) {
            logx('warn', 'csrf expired → reload');
            $_1 = Net::C("$host/mine.php", 'GET', null, $cookieFile, [], $host."/dashboard.php", $userAgent);
            continue;
        }

        if (($cla['new_clicks'] ?? 0) >= $_t['click_limit'] || str_contains($cla['message'], 'wait until the next reset')) {
            $withdraw = true;
            break;
        }

        $wait = $sle - $solveTime;
        if ($wait > 0) {
            sleep((int)ceil($wait));
        }
    } while(true);

    if ($withdraw) {
        logx('err', "[".date("H:i:s")."] withdraw");

        $dash = Net::C("$host/dashboard.php", 'GET', null, $cookieFile, [],$host."/mine.php", $userAgent);
        if ($dash) {
            $po = null;
            $f = xScraper::payload($dash);
            foreach ($f as $form) {
                if ($form['url'] === 'instant_withdrawal.php') {
                    $po = $form['payload'];
                    break;
                }
            }

            $r = rScraper::jPath($dash,'/remainingWithdrawalLtc\s*=\s*"([^"]+)"/');
            $remaining = $r[1][0] ?? null;
            preg_match('/[\d\.]+/', $remaining, $m);
            $remaining_ltc = (float)($m[0] ?? 0);

            $balNode = xScraper::xPath($dash, "//i[contains(@class,'fa-wallet')]/following::span[1]");
            if (!empty($balNode)) {
                preg_match('/[\d\.]+/',$balNode[0],$m);
                $balance = (float)$m[0];
                $amount_ltc = min($balance,$remaining_ltc);
                $amount = (int)($amount_ltc*100000000);
                if ($amount>0) {
                    $po['amount'] = $amount;
                    $c = capt::cha($dash);
                    $key = $c['keys'][0];
                    while(($t = _tK($host."/dashboard.php", $key)) === false);

                    $po['transaction_type'] = 'instant_withdraw';
                    $po['cf-turnstile-response'] = $t;
                    $res = Net::X("$host/instant_withdrawal.php", "POST", $po, $cookieFile, [], "$host/dashboard.php", $userAgent);
                    $msg = xScraper::xPath($res, "//div[@id='pageNotification']");

                    if (isset($msg[0])) {
                        logx('ok', "[".date("H:i:s")."] $mail::".$msg[0]);
                        if ($balance > 0) {
                            $waitMap = _loadW();
                            $next = ceil(time()/3600)*3600;
                            $waitMap[$mail] = $next;
                            _saveW($waitMap);
                            logx('info', "$mail wait until ".date('H:i:s', $next));
                        }
                    }
                }
            }
        }
    }
    
next_account:
    @unlink($cookieFile);
    $emailIndex++;
    if ($emailIndex >= $totalemail) {
        $emailIndex = 0;
    }
    $proxy = _nProxy($proxyIndex, $proxies);
    _sProxy($proxy);
}



















    
    








function _loadW() {
    $file = __DIR__.'/wait.json';
    if (!file_exists($file)) return [];
    return json_decode(file_get_contents($file), true) ?: [];
}

function _saveW($d) {
    $f = __DIR__.'/wait.json';
    file_put_contents($f, json_encode($d, JSON_PRETTY_PRINT));
}

function _sProxy($proxy) {
    list($h,$p,$u,$pw) = explode(':',$proxy);
    $raw = "http://$u:$pw@$h:$p";
    putenv("PROXY=$raw");
    $_ENV['PROXY'] = $raw;

    proxyLoad();
    #logx('info', "[ $u::$pw ]");
    $geo = getGeo();
    if ($geo && !empty($geo['ip'])) {
        logx('info', "{$geo['ip']}::", false, true);
        logx('ok', "{$geo['timezone']}", true, true);
        return true;
    }

    logx('err', "proxy failed");
    return false;
}

function _nProxy(&$proxyIndex,$proxies) {
    $proxyIndex++;

    if ($proxyIndex >= count($proxies)) {
        $proxyIndex = 0;
    }
    return $proxies[$proxyIndex];
}

function _tK($host, $keys) {
    logx('warn', 'solving turnstile');

    $api = getenv("CAPTCHA_APIKEY");

    $old = $GLOBALS['_CTX']['proxy'] ?? null;
    unset($GLOBALS['_CTX']['proxy']);
    
    $base = "https://gmxch-to.hf.space";

    $payload = [
        'type' => 'cloudflare',
        "method" => "turnstile",
        "siteKey" => $keys,
        "domain"  => $host
    ];
    $res = json_decode(
        Net::X("$base/solve", "POST", $payload, null, ["key: $api"], '', null, true) ?: '', 
        true
    );

    if (isset($res['error'])) {
        if ($old) $GLOBALS['_CTX']['proxy'] = $old;
        print_r($res);
        return false;
    }

    $taskId = $res['taskId'];

    for ($i=0;$i<35;$i++) {
        sleep(3);

        $r = json_decode(
            Net::X("$base/task", "POST",["taskId" => $taskId], null, ["key: $api"], '', null, true) ?: '',
            true
        );

        $s = $r['status'] ?? '';

        if ($s === 'done') {
            if ($old) $GLOBALS['_CTX']['proxy'] = $old;
            return $r['token'] ?? $r;
        }

        if ($s === 'error') {
            if ($old) $GLOBALS['_CTX']['proxy'] = $old;
            print_r($r);
            return false;
        }
    }

    if ($old) $GLOBALS['_CTX']['proxy'] = $old;
    return false;
}}
