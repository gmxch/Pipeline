<?php

$GLOBALS['_CTX'] ??= [];

styler:
{
define("ANN", "\033["); 
define("RSET", ANN."0m"); define("BOLD", ANN."1m");

define("FGb", [
  "BLK" => ANN."90m", "RED" => ANN."91m",
  "GRN" => ANN."92m", "YLW" => ANN."93m",
  "BLU" => ANN."94m", "MAG" => ANN."95m",
  "CYN" => ANN."96m", "WHT" => ANN."97m",
]);

function logx($i = "", $msg = "\n", $n = true, $b = false) {
    $b = $b ? BOLD : '';

    switch (strtoupper($i)) {
        case 'ERR': $p = BOLD.FGb['RED'];  break;
        case 'INFO': $p = $b.FGb['CYN']; break;
        case 'WARN': $p = $b.FGb['YLW']; break;
        case 'OK': $p = $b.FGb['GRN']; break;
        default: $p = $b.FGb['WHT']; break;
    }

    $out = $p.$msg.RSET.($n ? PHP_EOL : '');
    print($out);
    fflush(STDOUT);
}
}

class Net {

    private static function applyProxy($ch, $url) {
        proxyEnsure();
        if (!empty($GLOBALS['_CTX']['proxy'])) {
            #logx('info', 'proxied', true, true);
            $p = $GLOBALS['_CTX']['proxy'];
            curl_setopt($ch, CURLOPT_PROXY, $p['host']);
            curl_setopt($ch, CURLOPT_PROXYPORT, $p['port']);
            curl_setopt($ch, CURLOPT_PROXYTYPE, $p['type']);
            if (!empty($p['auth'])) {
                curl_setopt($ch, CURLOPT_PROXYUSERPWD, $p['auth']);
            }
            $i = stripos($url, 'https://') === 0;
            
            if ($p['type'] === CURLPROXY_HTTP || (defined('CURLPROXY_HTTPS') && $p['type'] === CURLPROXY_HTTPS)) {
                curl_setopt($ch, CURLOPT_HTTPPROXYTUNNEL, $i);
            }
        }
    }

    private static function Http(array $opt, $in = false, $fresh = false) {
        
        #GET
        $type = strtoupper($opt['type']);
        if ($type === 'GET' && !empty($opt['data']) && is_array($opt['data'])) {
            $qs = http_build_query($opt['data']);
            if ($qs !== '') {
                $opt['url'] .= (str_contains($opt['url'], '?') ? '&' : '?') . $qs;
            }
        }

        #URL
        if (empty($opt['url']) || !is_string($opt['url'])) {
            logx('err', 'invalid url'); return null;
        }
        $ch = curl_init($opt['url']);
        #var_dump($opt['url']);
        if (!$ch) { logx('err', 'init failed'); return null; }

        #PROXY
        self::applyProxy($ch, $opt['url']);

        #HTTP2
        $insecure = $in;
        $httpVer = CURL_HTTP_VERSION_1_1;
        if (!empty($opt['http2']) && !$insecure) {
            $httpVer = CURL_HTTP_VERSION_2TLS;
        }

        #INIT
        curl_setopt_array($ch, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_FOLLOWLOCATION => $opt['follow'],
            CURLOPT_CONNECTTIMEOUT => 30,
            CURLOPT_TIMEOUT => 30,
            CURLOPT_USERAGENT => $opt['ua'],
            CURLOPT_REFERER => $opt['ref'],
            CURLOPT_HTTPHEADER => $opt['head'],
            CURLOPT_SSL_VERIFYPEER => !$insecure,
            CURLOPT_SSL_VERIFYHOST => $insecure ? 0 : 2,
            CURLOPT_HTTP_VERSION => $httpVer,
            CURLOPT_FORBID_REUSE => $fresh,
            CURLOPT_FRESH_CONNECT => $fresh,
            CURLOPT_ENCODING => '',
        ]);

        #VERBOSE
        $logFile = null;
        if (!empty($opt['verbose'])) {
            $logFile = fopen(LIBDIR . "/verbose.log", "a");
            curl_setopt($ch, CURLOPT_VERBOSE, true);
            curl_setopt($ch, CURLOPT_STDERR, $logFile);
        }
        
        #DNS_CONNECT
        if (!empty($opt['connect'])) {
            curl_setopt($ch, CURLOPT_CONNECT_TO, $opt['connect']);
        }
        
        #DNS_RESOLVE
        if (!empty($opt['resolve'])) {
            curl_setopt($ch, CURLOPT_RESOLVE, $opt['resolve']);
        }

        #HEADERS
        $headr = [];
        curl_setopt($ch, CURLOPT_HEADERFUNCTION, function($ch, $line) use (&$headr) {
            $len = strlen($line); $line = trim($line);
            if ($line === '' || stripos($line, 'HTTP/') === 0) return $len;
            if (!str_contains($line, ':')) return $len;
            [$k, $v] = array_map('trim', explode(':', $line, 2));
            $headr[strtolower($k)][] = $v; return $len;
        });

        #COOKIE
        if (!empty($opt['cookie'])) {
            curl_setopt($ch, CURLOPT_COOKIEJAR, $opt['cookie']);
            curl_setopt($ch, CURLOPT_COOKIEFILE, $opt['cookie']);
        }

        #METHOD
        if ($type === 'HEAD') {
            curl_setopt($ch, CURLOPT_NOBODY, true);
        } elseif ($type !== 'GET') {
            if ($type === 'POST') {
                curl_setopt($ch, CURLOPT_POST, true);
            } else {
                curl_setopt($ch, CURLOPT_CUSTOMREQUEST, $type);
            } 
            if (isset($opt['data'])) {
                $payload = is_array($opt['data']) ? (!empty($opt['isJson']) ? json_encode($opt['data']) : http_build_query($opt['data'])) : $opt['data'];
                #var_dump($payload);
                curl_setopt($ch, CURLOPT_POSTFIELDS, $payload);
            }
        } 

        #EXEC
        try {
            for ($attempt = 0; $attempt <= 3; $attempt++) {
                $body = curl_exec($ch);
                $info = curl_getinfo($ch);
                $errno = curl_errno($ch);
                $err = curl_error($ch);
                
                if ($body !== false) {
                    if (!empty($opt['debug'])) {
                        return [
                            'http_code' => $info['http_code'] ?? null,
                            'url' => $info['url'] ?? null,
                            'headers' => $headr ?? null,
                            'errno' => $errno ?: null,
                            'error' => $err ?: null,
                            'info' => $info,
                            'body' => $body,
                            ];
                    } return $body;
                }

                if ($attempt > 0 && in_array($errno, [56, 92], true)) {
                    curl_setopt($ch, CURLOPT_HTTP_VERSION, CURL_HTTP_VERSION_1_1);
                }

                $retry = in_array($errno, [28, 35, 52, 56, 92], true);
                if (!$retry || $attempt === 3) {
                    throw new Exception("Net($errno): $err");
                } usleep(random_int(25, 50) * 10000);
            } throw new Exception("failed");
        } catch (Throwable $e) {
            logx('info', "{$e->getMessage()}", true, true);
            return null;
        } finally { 
            if (is_resource($logFile)) { fclose($logFile); }
            $ch = null; #unset($ch); #curl_close($ch)
        }
        
    }

    public static function C($url, $type, $data = null, $cookie = null, array $head = [], $reff = '', $ua = 'Mozilla/5.0', $d = false, $v = false, $ip = null, $foll = true, $ins = false, $f= false) {
        
        $dns = [];
        $connect = [];
        if (!empty($ip)) {
            $dom = parse_url($url, PHP_URL_HOST);
            if (!empty($GLOBALS['_CTX']['proxy'])) {
                $connect = ["$dom:443:$ip:443"];
            } else {
                $dns = ["$dom:80:$ip", "$dom:443:$ip"];
            }
        }
        $head[] = "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8";
        if (in_array($type, ['POST','PUT','PATCH'], true)) {
            $head[] = "Content-Type: application/x-www-form-urlencoded";
        }
            
        return self::Http([
            'url' => $url,
            'type' => $type,
            'data' => $data,
            'cookie' => $cookie,
            'head' => $head,
            'ref' => $reff,
            'ua' => $ua,
            'verbose' => $v,
            'debug' => $d,
            'follow' => $foll,
            'resolve' => $dns,
            'connect' => $connect,
        ], $ins, $f);
    }

    public static function X($url, $type, $data = null, $cookie = null, array $head = [], $reff = '', $ua = 'Mozilla/5.0', $json = false, $foll = true, $ip = null, $ins = false) {
                
        $dns = [];
        $connect = [];
        if (!empty($ip)) {
            $dom = parse_url($url, PHP_URL_HOST);
            if (!empty($GLOBALS['_CTX']['proxy'])) {
                $connect = ["$dom:443:$ip:443"];
            } else {
                $dns = ["$dom:80:$ip", "$dom:443:$ip"];
            }
        }
        
        if ($json && in_array($type, ['POST','PUT','PATCH'], true)) {
            $head[] = 'Content-Type: application/json';
            $head[] = 'Accept: application/json, text/javascript';
        } else {
            $head[] = 'Accept: */*';
            $head[] = 'Content-Type: application/x-www-form-urlencoded';
        }
        
        return self::Http([
            'url' => $url,
            'type' => $type,
            'data' => $data,
            'cookie' => $cookie,
            'head' => array_merge(['X-Requested-With: XMLHttpRequest'], $head),
            'ref' => $reff,
            'ua' => $ua,
            'isJson' => $json,
            'follow' => $foll,
            'resolve' => $dns,
            'connect' => $connect,
            'http2' => true,
            #'debug' => $d,
        ], $ins, false);
    }
}

proxy:
{
function proxyLoad() {

    $raw = trim(getenv('PROXY'));

    if ($raw === '') {
        proxyDisable();
        return;
    }

    $u = parse_url($raw);
    if (!$u || empty($u['scheme'])) {
        logx('err', "invalid PROXY");
        return;
    }

    $scheme = strtolower($u['scheme']);

    if (!empty($GLOBALS['_CTX']['proxy']) &&
        ($GLOBALS['_CTX']['proxy']['src'] ?? '') === $raw) {
        return;
    }

    if (empty($u['host']) || empty($u['port'])) {
        logx('err', "invalid PROXY");
        return;
    }

    $ptype = match($scheme) {
        'socks5', 'socks' => CURLPROXY_SOCKS5_HOSTNAME,
        'https' => (defined('CURLPROXY_HTTPS') ? CURLPROXY_HTTPS : CURLPROXY_HTTP),
        'http'  => CURLPROXY_HTTP,
        default => null,
    };

    if ($ptype === null) {
        logx('err', "unsupported proxy scheme");
        return;
    }

    $auth = null;
    if (!empty($u['user'])) {
        $auth = $u['user'] . ':' . ($u['pass'] ?? '');
    }

    $GLOBALS['_CTX']['proxy'] = [
        'host' => $u['host'],
        'port' => $u['port'],
        'type' => $ptype,
        'auth' => $auth,
        'src'  => $raw,
        'mode' => 'direct',
    ];
}

function proxyDisable() {
    putenv("PROXY=");
    $_ENV['PROXY'] = '';
    unset($GLOBALS['_CTX']['proxy']);
}

function proxyEnsure() {
    if (empty($GLOBALS['_CTX']['proxy'])) {
        proxyLoad();
    }
}

function getGeo() {

    $u = [
        'ipinfo'  => 'https://ipinfo.io/json',
        'ipapi'   => 'http://ip-api.com/json/',
        'geojs'   => 'https://get.geojs.io/v1/ip/geo.json',
        'ipwhois' => 'https://ipwhois.app/json/',
    ];

    $mappings = [
        'ipinfo'  => ['timezone','country','country','ip'],
        'ipapi'   => ['timezone','country','countryCode','query'],
        'geojs'   => ['timezone','country','country_code','ip'],
        'ipwhois' => ['timezone','country','country_code','ip'],
    ];

    foreach ($u as $service => $url) {
        $j = Net::C($url, 'GET', null, null, [], '', 'Mozilla/5.0');
        if (!is_string($j) || $j === '') continue;
        $data = json_decode($j, true);
        if (!is_array($data)) continue;
        [$tz, $c, $cc, $ip] = $mappings[$service];
        if (!empty($data[$ip])) {
            return [
                'ip' => $data[$ip] ?? null,
                'timezone' => $data[$tz] ?? null,
                'country' => $data[$c] ?? null,
                'country_code' => $data[$cc] ?? null
            ];
        }
    }

    return false;
}
}

scraper:
{
class capt {
    public static function cha($html): ?array {
        $xp = xScraper::dom($html);

        #recaptcha2
        $v2 = xScraper::xPath($xp, "//div[contains(@class,'g-recaptcha')]/@data-sitekey");
        if (!empty($v2)) {
            #compat
            foreach ($xp->query("//script[@src]") as $script) {
                $src = $script->getAttribute('src');
                if (strpos($src, 'challenges.cloudflare.com/turnstile') !== false) {
                    return ['type' => 'cft', 'keys' => $v2];
                }
            }
            return ['type' => 'rc2', 'keys' => $v2];
        }

        #recaptcha3
        $v3 = [];
        foreach ($xp->query("//script[@src]") as $script) {
            $src = $script->getAttribute('src');
            if (preg_match('/recaptcha\/api\.js\?render=([^&]+)/', $src, $m)) {
                $v3[] = $m[1];
            }
        }
        if (!empty($v3) || preg_match('/grecaptcha\.execute/', $html)) {
            return ['type' => 'rc3', 'keys' => $v3];
        }

        #turnstile (native)
        $turnstile = xScraper::xPath($xp, "//div[contains(@class,'cf-turnstile')]/@data-sitekey");
        foreach ($xp->query("//script[@src]") as $script) {
            $src = $script->getAttribute('src');
            if (preg_match('/challenges\.cloudflare\.com\/turnstile.*sitekey=([^&]+)/', $src, $m)) {
                $turnstile[] = $m[1];
            }
        }
        if (!empty($turnstile)) {
            return ['type' => 'cft', 'keys' => $turnstile];
        }

        #hcaptcha
        $hcaptcha = [];
        $hcaptcha = array_merge($hcaptcha, xScraper::xPath($xp, "//h-captcha/@site-key"));
        $hcaptcha = array_merge($hcaptcha, xScraper::xPath($xp, "//div[contains(@class,'h-captcha')]/@data-sitekey"));
        if (!empty($hcaptcha)) {
            return ['type' => 'hc', 'keys' => $hcaptcha];
        }

        #RsCaptcha
        $rsc = [];
        foreach ($xp->query("//script[@src]") as $script) {
            $src = $script->getAttribute('src');
            if (preg_match('/rscaptcha\.com.*\?(.*)$/', $src, $m)) {
                parse_str($m[1], $params);
                if (!empty($params['app_id']) && !empty($params['public_key']) && !empty($params['version'])) {
                    $ver = preg_replace('/^v/', '', $params['version']);
                    $rsc[] = [
                        'version'    => $ver,
                        'app_id'     => $params['app_id'],
                        'public_key' => $params['public_key']
                    ];
                }
            }
        }
        if (!empty($rsc)) {
            return ['type' => 'rsc_'.$rsc[0]['version'], 'keys' => $rsc];
        }

        return null; // tidak terdeteksi
    }
}

class xScraper { #xdom based
    public static function dom($html): DOMXPath {
        libxml_use_internal_errors(true);
        $dom = new DOMDocument();
        if (!$html) {
            $dom->loadHTML("<html></html>");
        } else {
            $dom->loadHTML($html, LIBXML_NOWARNING | LIBXML_NOERROR | LIBXML_NONET);
        }
        return new DOMXPath($dom);
    }
    
    public static function payload($html): array {
        $xp = self::dom($html);
        $forms = $xp->query("//form");
        $out = [];
        foreach ($forms as $idx => $form) {
            $entry = [
                'url'     => $form->getAttribute('action'),
                'method'  => strtoupper($form->getAttribute('method') ?: 'GET'),
                'payload' => []
            ];
            // INPUT
            foreach ($xp->query(".//input[@name]", $form) as $input) {
                $name  = $input->getAttribute('name');
                $type  = strtolower($input->getAttribute('type') ?: 'text');
                $value = $input->getAttribute('value');

                if (in_array($type, ['checkbox', 'radio'], true)
                    && !$input->hasAttribute('checked')) {
                    continue;
                }
                $entry['payload'][$name] = $value !== '' ? $value : '';
            }

            // SELECT
            foreach ($xp->query(".//select[@name]", $form) as $select) {
                $name = $select->getAttribute('name');

                $opt = $xp->query(".//option[@selected]", $select)->item(0)
                    ?? $xp->query(".//option", $select)->item(0);
                
                if (!isset($entry['payload'][$name])) {
                    $entry['payload'][$name] = $opt ? $opt->getAttribute('value') : '';
                }

                #$entry['payload'][$name] = $opt ? $opt->getAttribute('value') : '';
            }

            // TEXTAREA
            foreach ($xp->query(".//textarea[@name]", $form) as $ta) {
                $entry['payload'][$ta->getAttribute('name')] =
                    trim($ta->textContent);
            }

            $out[] = $entry;
        }
        return $out;
    }
    
    public static function xPath ($html, $query):array {
        $xpath = $html instanceof DOMXPath ? $html : self::dom($html);
        $nodes = $xpath->query($query);
        $out = [];
        foreach ($nodes as $node) {
        // Attribute $node
            if ($node instanceof DOMAttr) { $out[] = $node->value; }
        // Element / Text node
            else { $out[] = trim($node->textContent); }
        } return $out;
    }
    
    
}

class rScraper { #regex based
    public static function pPath($html, $target): array {
        $t = preg_quote($target, '/');
        $pattern = "/{$t}\s*=\s*[\"']([^\"']+)[\"']/";
        preg_match_all($pattern, $html, $m);
        return $m;
    }
    public static function jPath($code, $pattern): ?array {
        preg_match_all($pattern, $code, $match);
        return $match;
    }
} 
}