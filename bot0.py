import requests
import time
import re
import json
import random
import string
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import logging
import sys
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from colorama import init, Fore, Style
import os
import threading
from queue import Queue
from typing import List, Optional, Tuple

# ===== MATRIX WORKER SUPPORT =====
WORKER_ID = int(os.getenv("WORKER_ID", 0))
WORKER_TOTAL = int(os.getenv("WORKER_TOTAL", 1))

# ================= INIT COLORAMA =================
init(autoreset=True)

# ========== KONFIGURASI WARNA ANSI ==========
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

# ========== KONFIGURASI LOGGING DENGAN WARNA ==========
class ColoredFormatter(logging.Formatter):
    def format(self, record):
        original_levelname = record.levelname
        if record.levelname == 'INFO':
            record.levelname = f"{Colors.OKBLUE}{record.levelname}{Colors.ENDC}"
        elif record.levelname == 'WARNING':
            record.levelname = f"{Colors.WARNING}{record.levelname}{Colors.ENDC}"
        elif record.levelname == 'ERROR':
            record.levelname = f"{Colors.FAIL}{record.levelname}{Colors.ENDC}"
        
        result = super().format(record)
        if "✅" in result:
            result = f"{Colors.OKGREEN}{result}{Colors.ENDC}"
        record.levelname = original_levelname
        return result

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger(__name__)
for handler in logger.handlers[:]:
    logger.removeHandler(handler)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(ColoredFormatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%H:%M:%S'))
logger.addHandler(handler)
logger.propagate = False

# ========== KONFIGURASI TAMPILAN ==========
SHOW_EMAIL_IN_LOOP = False
USE_ACCOUNT_ID = True

def log_info(msg, email=None, account_id=None):
    if email and SHOW_EMAIL_IN_LOOP:
        prefix = f"[{email}] "
    elif account_id and USE_ACCOUNT_ID:
        prefix = f"[#{account_id}] "
    else:
        prefix = ""
    logger.info(f"{prefix}{msg}")

def log_success(msg, email=None, account_id=None):
    if email and SHOW_EMAIL_IN_LOOP:
        prefix = f"[{email}] "
    elif account_id and USE_ACCOUNT_ID:
        prefix = f"[#{account_id}] "
    else:
        prefix = ""
    logger.info(f"{prefix}✅ {msg}")

def log_error(msg, email=None, account_id=None):
    if email and SHOW_EMAIL_IN_LOOP:
        prefix = f"[{email}] "
    elif account_id and USE_ACCOUNT_ID:
        prefix = f"[#{account_id}] "
    else:
        prefix = ""
    logger.error(f"{prefix}{msg}")

def log_warning(msg, email=None, account_id=None):
    if email and SHOW_EMAIL_IN_LOOP:
        prefix = f"[{email}] "
    elif account_id and USE_ACCOUNT_ID:
        prefix = f"[#{account_id}] "
    else:
        prefix = ""
    logger.warning(f"{prefix}{msg}")

# ========== FUNGSI HELPER UNTUK COOLDOWN JAM BERIKUTNYA (FALLBACK) ==========
def time_until_next_hour():
    now = datetime.now()
    next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    return (next_hour - now).total_seconds()

# ========== KONFIGURASI UMUM ==========
BASE_URL = "https://litecoinfarm.online"
ROLL_URL = f"{BASE_URL}/mine.php"
WITHDRAW_URL = f"{BASE_URL}/dashboard.php"
INSTANT_WITHDRAW_URL = f"{BASE_URL}/instant_withdrawal.php"
BASE_URL1 = "https://litecoinfarm.online/index.php?ref=413930"

# Konfigurasi solver (satu solver)
SOLVER_URL = os.getenv("SOLVER_URL", "https://gmxch-to.hf.space")
SOLVER_KEY = os.getenv("SOLVER_KEY", "gamamoch4262")

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
MIN_WITHDRAW = 0.00005000
WITHDRAW_ALL = True
FIXED_WITHDRAW_AMOUNT = 0.00005000

MAX_RETRIES = 3
BACKOFF_FACTOR = 0.5
REQUEST_TIMEOUT = 25

# ========== PROXY FILE MONITOR ==========
PROXY_FILE = "proxies.txt"
last_proxy_file_mtime = 0
proxy_reload_interval = 30

# ========== KELAS UNTUK MENYIMPAN DATA AKUN ==========
class AccountData:
    def __init__(self, email):
        self.email = email
        self.account_id = 0
        self.hourly_limit = 0.0
        self.hourly_remaining = 0.0
        self.hourly_reset = 0
        self.withdrawn_today = 0.0
        self.bonus_done_today = False  # Flag untuk bonus 50x (ganti dari mining_done)
        self.bonus_reset = 0
        self.referrals = 0
        self.last_activity = 0
        self.total_withdrawn = 0.0
        self.last_balance = 0.0
        self.assigned_proxy = None
        self.withdraw_limit_reached = False
        self.all_empty = False
        self.last_all_empty_time = 0
        self.hourly_cooldown = None
        self.bonus_cooldown = None
    
    def can_withdraw_now(self):
        now = time.time()
        if self.hourly_reset > 0 and now >= self.hourly_reset:
            self.hourly_remaining = self.hourly_limit
            self.hourly_reset = 0
            return True
        return self.hourly_remaining > 0 and self.hourly_reset == 0
    
    def mark_withdraw_done(self, amount):
        self.hourly_remaining = max(0, self.hourly_remaining - amount)
        if self.hourly_remaining <= 0:
            self.hourly_reset = time.time() + 3600
        self.total_withdrawn += amount
    
    def can_do_bonus_today(self):
        now = time.time()
        if self.bonus_reset > 0 and now >= self.bonus_reset:
            self.bonus_done_today = False
            self.bonus_reset = 0
        return not self.bonus_done_today
    
    def mark_bonus_done(self):
        self.bonus_done_today = True
        self.bonus_reset = time.time() + 86400
    
    def get_wait_time(self):
        now = time.time()
        if self.hourly_reset > now:
            return self.hourly_reset - now
        return 0

# ========== PROXY MANAGER DENGAN DEDICATED PROXY PER AKUN ==========
class ProxyManager:
    def __init__(self, proxy_list: List[str] = None):
        self.fresh_proxies = Queue()
        self.failed_proxies = set()
        self.lock = threading.Lock()
        self.all_proxies = []
        self.account_proxy_mapping = {}
        self.proxy_account_mapping = {}
        self.ever_used_proxies = set()
        
        if proxy_list:
            self.add_fresh_proxies(proxy_list)
    
    def add_fresh_proxies(self, proxy_list: List[str]):
        with self.lock:
            valid_proxies = []
            for proxy in proxy_list:
                if proxy and self._validate_proxy_format(proxy):
                    if proxy not in self.all_proxies and proxy not in self.failed_proxies:
                        valid_proxies.append(proxy)
                        self.all_proxies.append(proxy)
            
            for proxy in valid_proxies:
                self.fresh_proxies.put(proxy)
                log_info(f"📦 Proxy FRESH siap: {proxy}")
            
            if valid_proxies:
                log_success(f"✅ {len(valid_proxies)} proxy FRESH baru ditambahkan")
    
    def reload_from_file(self, filepath=PROXY_FILE):
        try:
            with open(filepath, 'r') as f:
                new_proxies = [line.strip() for line in f if line.strip()]
            
            really_new = []
            with self.lock:
                for proxy in new_proxies:
                    if proxy not in self.all_proxies and proxy not in self.failed_proxies:
                        really_new.append(proxy)
            
            if really_new:
                self.add_fresh_proxies(really_new)
                return True
            return False
        except FileNotFoundError:
            return False
        except Exception as e:
            log_error(f"Gagal reload proxy: {e}")
            return False
    
    def _validate_proxy_format(self, proxy: str) -> bool:
        parts = proxy.split(':')
        return len(parts) in [2, 4]
    
    def _is_absolutely_fresh(self, proxy: str) -> bool:
        return (proxy not in self.ever_used_proxies and 
                proxy not in self.failed_proxies and
                proxy not in self.proxy_account_mapping)
    
    def assign_proxy_to_account(self, account_id: int, account_email: str = "") -> Optional[str]:
        with self.lock:
            if account_id in self.account_proxy_mapping:
                proxy = self.account_proxy_mapping[account_id]
                if proxy not in self.failed_proxies:
                    if self.proxy_account_mapping.get(proxy) == account_id:
                        log_info(f"🔄 Akun #{account_id} menggunakan proxy tetap: {proxy}")
                        return proxy
                    else:
                        log_error(f"❌ KRITIS: Mapping corrupt untuk akun #{account_id}!")
                        del self.account_proxy_mapping[account_id]
                else:
                    log_warning(f"⚠️ Proxy {proxy} untuk akun #{account_id} sudah mati")
                    if account_id in self.account_proxy_mapping:
                        del self.account_proxy_mapping[account_id]
                    if proxy in self.proxy_account_mapping:
                        del self.proxy_account_mapping[proxy]
            
            if self.fresh_proxies.empty():
                log_error(f"❌ TIDAK ADA PROXY FRESH UNTUK AKUN #{account_id}!")
                log_error(f"   🔴 TAMBAHKAN PROXY BARU DI {PROXY_FILE}!")
                return None
            
            proxy = self.fresh_proxies.get()
            
            if not self._is_absolutely_fresh(proxy):
                log_error(f"❌ KRITIS: Proxy {proxy} TIDAK FRESH!")
                return self.assign_proxy_to_account(account_id, account_email)
            
            self.account_proxy_mapping[account_id] = proxy
            self.proxy_account_mapping[proxy] = account_id
            self.ever_used_proxies.add(proxy)
            
            email_info = f"({account_email}) " if account_email else ""
            log_success(f"✅ Akun #{account_id} {email_info}→ Proxy FRESH: {proxy}")
            
            sisa = self.fresh_proxies.qsize()
            if sisa > 0:
                log_info(f"📦 Sisa proxy FRESH: {sisa}")
            else:
                log_warning(f"⚠️ STOK FRESH HABIS! {len(self.account_proxy_mapping)} akun terpakai")
            
            return proxy
    
    def mark_proxy_failed(self, proxy: str, account_id: int):
        with self.lock:
            if self.proxy_account_mapping.get(proxy) != account_id:
                log_error(f"❌ KRITIS: Proxy {proxy} BUKAN milik akun #{account_id}!")
                return
            
            log_warning(f"⚠️ Proxy {proxy} GAGAL total untuk akun #{account_id}")
            self.failed_proxies.add(proxy)
            
            if account_id in self.account_proxy_mapping:
                del self.account_proxy_mapping[account_id]
            if proxy in self.proxy_account_mapping:
                del self.proxy_account_mapping[proxy]
            
            log_info(f"🔄 Akun #{account_id} akan mencari proxy FRESH pengganti...")
    
    def get_proxy_for_account(self, account_id: int, account_email: str = "") -> Optional[str]:
        return self.assign_proxy_to_account(account_id, account_email)
    
    def get_stats(self) -> dict:
        with self.lock:
            return {
                'fresh': self.fresh_proxies.qsize(),
                'failed': len(self.failed_proxies),
                'assigned': len(self.account_proxy_mapping),
                'total_all': len(self.all_proxies),
                'ever_used': len(self.ever_used_proxies)
            }

# ========== ACCOUNT POOL DENGAN 2 FASE ==========
class AccountPool:
    def __init__(self, email_list: List[str]):
        self.accounts = []
        for i, email in enumerate(email_list):
            acc = AccountData(email)
            acc.account_id = i + 1
            self.accounts.append(acc)
        
        self.current_index = 0
        self.lock = threading.Lock()
        self.total_processed = 0
        self.current_phase = "BONUS"  # BONUS atau WITHDRAW_ONLY
    
    def get_next_account(self):
        with self.lock:
            now = time.time()

            # ======================
            # FASE 1: BONUS
            # ======================
            if self.current_phase == "BONUS":
                for i in range(len(self.accounts)):
                    idx = (self.current_index + i) % len(self.accounts)
                    account = self.accounts[idx]

                    if not account.bonus_done_today:
                        self.current_index = (idx + 1) % len(self.accounts)
                        return account, "BONUS"

                log_success("\n" + "="*60)
                log_success("✅ SEMUA AKUN SELESAI FASE BONUS 50x!")
                log_success("🔄 MEMASUKI FASE 2 - WITHDRAW SETIAP JAM...")
                self.current_phase = "WITHDRAW_ONLY"
                self.current_index = 0

            # ======================
            # FASE 2: WITHDRAW
            # ======================
            if self.current_phase == "WITHDRAW_ONLY":

                # reset akun yang waktunya sudah lewat
                for acc in self.accounts:
                    if acc.hourly_reset > 0 and now >= acc.hourly_reset:
                        acc.hourly_remaining = acc.hourly_limit
                        acc.hourly_reset = 0
                        log_info(f"♻️ Reset limit akun #{acc.account_id}")

                # cari akun yang bisa withdraw
                start_idx = self.current_index

                for i in range(len(self.accounts)):
                    idx = (start_idx + i) % len(self.accounts)
                    account = self.accounts[idx]

                    if account.hourly_remaining > 0:
                        self.current_index = (idx + 1) % len(self.accounts)
                        self.total_processed += 1
                        return account, "WITHDRAW"

                # ======================
                # semua akun habis limit
                # ======================
                min_wait = float('inf')

                for account in self.accounts:
                    if account.hourly_reset > now:
                        wait = account.hourly_reset - now
                        if wait < min_wait:
                            min_wait = wait

                if min_wait < float('inf'):
                    min_wait = min(min_wait, 3600)

                    log_info("\n⏰ Semua akun habis limit per jam.")

                    total_seconds = int(min_wait)

                    for remaining in range(total_seconds, 0, -1):

                        mins = remaining // 60
                        secs = remaining % 60

                        ready = sum(
                            1 for acc in self.accounts
                            if acc.hourly_remaining > 0 or acc.hourly_reset <= time.time()
                        )

                        waiting = len(self.accounts) - ready

                        sys.stdout.write('\r' + ' ' * 100 + '\r')
                        sys.stdout.write(
                            f"⏳ Reset limit dalam {mins:02d}:{secs:02d} | Siap: {ready} | Menunggu: {waiting}"
                        )
                        sys.stdout.flush()

                        time.sleep(1)

                    print()

                    return self.get_next_account()

                else:
                    time.sleep(60)
                    return self.get_next_account()
    
    def get_progress(self):
        with self.lock:
            now = time.time()
            bonus_done = sum(1 for acc in self.accounts if acc.bonus_done_today)
            
            can_withdraw = 0
            waiting = 0
            waiting_details = []
            
            for acc in self.accounts:
                if acc.hourly_remaining > 0:
                    can_withdraw += 1
                elif acc.hourly_reset > now:
                    waiting += 1
                    wait = acc.hourly_reset - now
                    waiting_details.append((acc.account_id, wait))
            
            waiting_details.sort(key=lambda x: x[1])
            
            return {
                'total': len(self.accounts),
                'bonus_done': bonus_done,
                'bonus_left': len(self.accounts) - bonus_done,
                'can_withdraw': can_withdraw,
                'waiting': waiting,
                'waiting_details': waiting_details[:5],
                'phase': self.current_phase
            }

# ========== BOT UTAMA (LOGIKA ASLI ANDA 100% UTUH) ==========
class LitecoinFarmBot:
    SITEKEY_LOGIN = "0x4AAAAAABVIgMF8F5Q4bDp4"
    SITEKEY_ROLL  = "0x4AAAAAACkcZ45jW4fbEjbd"

    def __init__(self, account_data: AccountData, proxy_manager: ProxyManager = None):
        self.account = account_data
        self.email = account_data.email
        self.account_id = account_data.account_id
        self.proxy_manager = proxy_manager
        self.proxy_string = None
        self.use_proxy = False
        self.session = None
        self.sitekey = self.SITEKEY_LOGIN
        self.stop_flag = False
        self.solver_url = SOLVER_URL
        self.login_sitekey = None
        self.roll_sitekey = None
        self.withdraw_sitekey = None
        
        # Pindahkan state dari account ke instance bot
        self.withdraw_limit_reached = account_data.withdraw_limit_reached
        self.all_empty = account_data.all_empty
        self.last_all_empty_time = account_data.last_all_empty_time
        self.hourly_cooldown = account_data.hourly_cooldown
        self.account.hourly_reset = self.hourly_cooldown
        self.bonus_cooldown = account_data.bonus_cooldown
        
        # Variabel untuk menyimpan state
        self.html = None
        self.mine_csrf = None
        self.balance = None
        self.hourly_remaining = 0
        
        self.session = self._create_session()
        log_info(f"Menggunakan solver: {self.solver_url}", self.email, self.account_id)
    
    def _get_new_proxy(self) -> bool:
        if not self.proxy_manager:
            self.use_proxy = False
            return True
        
        if self.account.assigned_proxy:
            log_info(f"🔄 Akun #{self.account_id} menggunakan proxy tetap: {self.account.assigned_proxy}")
        
        self.proxy_string = self.proxy_manager.get_proxy_for_account(self.account_id, self.email)
        
        if self.proxy_string:
            self.use_proxy = True
            self.account.assigned_proxy = self.proxy_string
            return self._setup_proxy()
        else:
            log_error(f"❌ TIDAK ADA PROXY UNTUK AKUN #{self.account_id}!", self.email, self.account_id)
            self.use_proxy = False
            return False
    
    def _setup_proxy(self):
        try:
            parts = self.proxy_string.split(':')
            if len(parts) == 4:
                host, port, user, password = parts
                proxy_url = f"http://{user}:{password}@{host}:{port}"
            elif len(parts) == 2:
                host, port = parts
                proxy_url = f"http://{host}:{port}"
            else:
                log_error(f"❌ Format proxy salah", self.email, self.account_id)
                return False
            
            self.session.proxies = {
                "http": proxy_url,
                "https": proxy_url
            }
            log_info(f"✅ Proxy dikonfigurasi: {host}:{port}", self.email, self.account_id)
            return True
        except Exception as e:
            log_error(f"❌ Gagal konfigurasi proxy: {e}", self.email, self.account_id)
            return False
    
    def _handle_proxy_failure(self):
        if self.use_proxy and self.proxy_string and self.proxy_manager:
            log_error(f"❌ Proxy {self.proxy_string} gagal total untuk akun #{self.account_id}", self.email, self.account_id)
            self.proxy_manager.mark_proxy_failed(self.proxy_string, self.account_id)
            self.use_proxy = False
            self.session.proxies = {}
            self.account.assigned_proxy = None
            return self._get_new_proxy()
        return False

    def _create_session(self):
        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT})

        retry_strategy = Retry(
            total=2,
            connect=2,
            read=2,
            backoff_factor=0.3,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS", "POST"]
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)

        session.mount("http://", adapter)
        session.mount("https://", adapter)

        return session

    def http_request(self, method, url, **kwargs):
        kwargs.setdefault('timeout', REQUEST_TIMEOUT)
        for attempt in range(1, MAX_RETRIES + 2):
            try:
                resp = self.session.request(method, url, **kwargs)
                if resp.status_code >= 500:
                    raise requests.exceptions.HTTPError(f"Server error {resp.status_code}")
                return resp
            except (requests.exceptions.RequestException, requests.exceptions.HTTPError) as e:
                log_warning(f"Request {method} {url} gagal (percobaan {attempt}): {e}", self.email, self.account_id)
                
                error_str = str(e).lower()
                is_proxy_error = any(x in error_str for x in [
                    'proxy', 'connection', 'remote', 'disconnect', 'timeout', 
                    'broken', 'closed', 'reset', 'refused', 'unreachable'
                ])
                
                if self.use_proxy and is_proxy_error and attempt >= 2:
                    if self._handle_proxy_failure():
                        continue
                
                if attempt <= MAX_RETRIES:
                    sleep_time = BACKOFF_FACTOR * (2 ** (attempt - 1))
                    log_info(f"Menunggu {sleep_time} detik sebelum mencoba lagi...", self.email, self.account_id)
                    time.sleep(sleep_time)
                else:
                    log_error(f"Semua percobaan gagal untuk {method} {url}", self.email, self.account_id)
                    raise
        return None

    # ========== FUNGSI EKSTRAKSI (SAMA PERSIS DENGAN SCRIPT ASLI) ==========
    def extract_sitekey(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        elem = soup.find(attrs={"data-sitekey": True})
        if elem:
            return elem['data-sitekey']
        for script in soup.find_all('script'):
            if script.string:
                match = re.search(r"sitekey\s*[:=]\s*['\"]([^'\"]+)['\"]", script.string)
                if match:
                    return match.group(1)
        return None

    def extract_csrf_token(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        csrf_input = soup.find('input', {'name': 'csrf_token'})
        if csrf_input:
            return csrf_input.get('value')
        match = re.search(r"let csrfToken\s*=\s*'([^']+)'", html)
        return match.group(1) if match else None

    def extract_request_id(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        rid_input = soup.find('input', {'name': 'request_id'})
        return rid_input.get('value') if rid_input else None

    def extract_clicks_data(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        clicks_span = soup.find('span', id='clicks_today')
        if clicks_span:
            text = clicks_span.text
            match = re.search(r'(\d+)/(\d+)', text)
            if match:
                return int(match.group(1)), int(match.group(2))
        return None, None

    def extract_balance(self, html):
        soup = BeautifulSoup(html, "html.parser")
        balance_span = soup.select_one("#balance")
        if balance_span:
            text = balance_span.get_text(" ", strip=True)
            match = re.search(r'([\d]+\.[\d]+)\s*LTC', text)
            if match:
                return float(match.group(1))
        balances = []
        for span in soup.find_all("span"):
            text = span.get_text(" ", strip=True)
            match = re.search(r'([\d]+\.[\d]+)\s*LTC', text)
            if match:
                try:
                    balances.append(float(match.group(1)))
                except:
                    pass
        if balances:
            return max(balances)
        return None

    def extract_reset_timer(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        timer_span = soup.find(id='resetTimer')
        if timer_span:
            text = timer_span.get_text(strip=True)
            match = re.search(r'(\d+):(\d+)', text)
            if match:
                minutes = int(match.group(1))
                seconds = int(match.group(2))
                return minutes * 60 + seconds
        timer_span = soup.find(id='hourResetTimer')
        if timer_span:
            text = timer_span.get_text(strip=True)
            match = re.search(r'(\d+):(\d+)', text)
            if match:
                minutes = int(match.group(1))
                seconds = int(match.group(2))
                return minutes * 60 + seconds
        return None

    def extract_error_from_html(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        swal = soup.find('div', class_='swal2-html-container')
        if swal:
            return swal.get_text(strip=True)
        error = soup.find('div', class_='notification error')
        if error:
            return error.get_text(strip=True)
        for script in soup.find_all('script'):
            if script.string and 'Swal.fire' in script.string:
                match = re.search(r"text:\s*'([^']+)'", script.string)
                if match:
                    return match.group(1)
        return None

    def extract_success_from_html(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        toast = soup.find('div', class_='toast') or soup.find('div', class_='alert-success') or soup.find('div', class_='success')
        if toast:
            return toast.get_text(strip=True)
        for script in soup.find_all('script'):
            if script.string and ('Swal.fire' in script.string or 'toast' in script.string) and ('success' in script.string.lower() or 'withdrawn' in script.string.lower()):
                match = re.search(r"text:\s*'([^']+)'", script.string)
                if match:
                    return match.group(1)
        if 'withdrawal successful' in html.lower() or 'successfully withdrawn' in html.lower():
            return "Withdrawal successful"
        return None

    def extract_hourly_limit_info(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        try:
            withdrawn = None
            hourly_limit = None
            remaining = None
            for p in soup.find_all('p'):
                text = p.get_text()
                if 'Withdrawn last hour:' in text:
                    match = re.search(r'Withdrawn last hour:\s*([\d.]+)\s*LTC', text)
                    if match:
                        withdrawn = float(match.group(1))
                if 'Hourly withdrawal limit:' in text:
                    match = re.search(r'Hourly withdrawal limit:\s*([\d.]+)\s*LTC', text)
                    if match:
                        hourly_limit = float(match.group(1))
                if 'Remaining this hour:' in text:
                    match = re.search(r'Remaining this hour:\s*([\d.]+)\s*LTC', text)
                    if match:
                        remaining = float(match.group(1))
            if withdrawn is None or hourly_limit is None or remaining is None:
                for div in soup.find_all('div'):
                    text = div.get_text()
                    if withdrawn is None and 'Withdrawn last hour:' in text:
                        match = re.search(r'Withdrawn last hour:\s*([\d.]+)\s*LTC', text)
                        if match:
                            withdrawn = float(match.group(1))
                    if hourly_limit is None and 'Hourly withdrawal limit:' in text:
                        match = re.search(r'Hourly withdrawal limit:\s*([\d.]+)\s*LTC', text)
                        if match:
                            hourly_limit = float(match.group(1))
                    if remaining is None and 'Remaining this hour:' in text:
                        match = re.search(r'Remaining this hour:\s*([\d.]+)\s*LTC', text)
                        if match:
                            remaining = float(match.group(1))
            if remaining is None and hourly_limit is not None and withdrawn is not None:
                remaining = hourly_limit - withdrawn
            if hourly_limit is None and withdrawn is not None and remaining is not None:
                hourly_limit = withdrawn + remaining
            if withdrawn is None and hourly_limit is not None and remaining is not None:
                withdrawn = hourly_limit - remaining
            if withdrawn is not None or hourly_limit is not None or remaining is not None:
                if hourly_limit is not None:
                    self.account.hourly_limit = hourly_limit
                if remaining is not None:
                    self.account.hourly_remaining = remaining
                    self.hourly_remaining = remaining
                return {
                    'withdrawn_last_hour': withdrawn,
                    'hourly_limit': hourly_limit,
                    'remaining_this_hour': remaining
                }
        except Exception as e:
            log_warning(f"Gagal mengekstrak info hourly limit: {e}", self.email, self.account_id)
        return None

    def solve_turnstile(self, domain, sitekey=None):
        if sitekey is None:
            sitekey = self.sitekey
        domain_with_proto = f"https://{domain}" if not domain.startswith('http') else domain
        headers = {"Content-Type": "application/json", "key": SOLVER_KEY}
        data = {"method": "turnstile", "type": "cloudflare", "domain": domain_with_proto, "siteKey": sitekey}
        for attempt in range(1, MAX_RETRIES + 5):
            try:
                resp = self.http_request("POST", f"{self.solver_url}/solve", headers=headers, json=data)
                result = resp.json()
                if "taskId" not in result:
                    log_error("Tidak ada taskId", self.email, self.account_id)
                    return None
                task_id = result["taskId"]
                for _ in range(30):
                    time.sleep(5)
                    poll = self.http_request("POST", f"{self.solver_url}/task", headers=headers, json={"taskId": task_id})
                    poll_res = poll.json()
                    if poll_res.get("status") == "done":
                        token = poll_res.get("token") or poll_res.get("solution", {}).get("token")
                        if token:
                            log_success("Token diterima", self.email, self.account_id)
                            return token
                    elif poll_res.get("status") == "error":
                        log_error(f"Error solver: {poll_res}", self.email, self.account_id)
                        return None
                log_error("Timeout polling", self.email, self.account_id)
                return None
            except Exception as e:
                log_warning(f"Solver error (percobaan {attempt}): {e}", self.email, self.account_id)
                if attempt <= MAX_RETRIES:
                    time.sleep(BACKOFF_FACTOR * (2 ** (attempt - 1)))
                else:
                    log_error("Gagal mendapatkan token dari solver setelah beberapa percobaan", self.email, self.account_id)
                    return None
        return None

    # ========== FUNGSI INTERAKSI (SAMA PERSIS DENGAN SCRIPT ASLI) ==========
    def submit_email(self, csrf_token, request_id, turnstile_token):
        data = {
            'faucet_email': self.email,
            'csrf_token': csrf_token,
            'request_id': request_id,
            'cf-turnstile-response': turnstile_token
        }
        log_info("Submitting email...", self.email, self.account_id)
        try:
            resp = self.http_request("POST", BASE_URL1, data=data, allow_redirects=True)
            if resp.status_code == 200:
                if "Email saved" in resp.text or "success" in resp.text.lower():
                    log_success("Email submitted", self.email, self.account_id)
                    return True
                else:
                    log_warning("Email submission may have failed, but continuing", self.email, self.account_id)
                    return True
            else:
                log_error(f"Email submission failed with status {resp.status_code}", self.email, self.account_id)
                return False
        except Exception as e:
            log_error(f"Exception saat submit email: {e}", self.email, self.account_id)
            return False

    def do_roll(self, csrf_token, turnstile_token):
        now = int(time.time() * 1000)
        rand_str = ''.join(random.choices(string.ascii_lowercase + string.digits, k=9))
        request_id = f"CLAIM_{now}_{rand_str}"
        data = {
            'mine_action': '1',
            'cf-turnstile-response': turnstile_token,
            'request_id': request_id,
            'csrf_token': csrf_token
        }
        headers = {"X-Requested-With": "XMLHttpRequest", "Referer": ROLL_URL}
        log_info("Mining...", self.email, self.account_id)
        try:
            resp = self.http_request("POST", ROLL_URL, data=data, headers=headers, allow_redirects=False)
            try:
                j = resp.json()
                return j
            except:
                error_msg = self.extract_error_from_html(resp.text)
                if error_msg:
                    log_error(f"Server: {error_msg}", self.email, self.account_id)
                else:
                    log_error("Respon tidak dikenal (bukan JSON)", self.email, self.account_id)
                return None
        except Exception as e:
            log_error(f"Exception saat mining: {e}", self.email, self.account_id)
            return None

    def do_withdraw_generic(self, url, data, headers=None):
        log_info(f"Withdraw request...", self.email, self.account_id)
        default_headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Referer": WITHDRAW_URL,
            "Content-Type": "application/x-www-form-urlencoded"
        }
        if headers:
            default_headers.update(headers)
        try:
            resp = self.http_request("POST", url, data=data, headers=default_headers, allow_redirects=True)
            if resp.status_code == 200:
                try:
                    j = resp.json()
                    return j
                except:
                    success_msg = self.extract_success_from_html(resp.text)
                    if success_msg:
                        log_success(Fore.GREEN + f"Withdraw sukses: {success_msg}", self.email, self.account_id)
                        return {'success': True, 'message': success_msg}
                    error_msg = self.extract_error_from_html(resp.text)
                    if not error_msg:
                        error_msg = "Unknown error (non-JSON response)"
                    return {'success': False, 'message': error_msg}
            else:
                return {'success': False, 'message': f"HTTP {resp.status_code}"}
        except Exception as e:
            return {'success': False, 'message': str(e)}

    def perform_withdraw(self, withdraw_url, form_data, amount, sitekey=None, currency='LTC'):
        if self.withdraw_limit_reached:
            log_info("Withdraw sudah limit hari ini, skip", self.email, self.account_id)
            return None
        data = form_data.copy()
        data.pop('email', None)
        if 'transaction_type' not in data:
            data['transaction_type'] = 'instant_withdraw'
        amount_integer = str(int(amount * 100_000_000))
        data['amount'] = amount_integer
        data['currency'] = currency
        if sitekey is None:
            sitekey = self.withdraw_sitekey or self.SITEKEY_ROLL
        turnstile_token = self.solve_turnstile(withdraw_url, sitekey=sitekey)
        if not turnstile_token:
            log_error("Gagal mendapat token Turnstile untuk withdraw", self.email, self.account_id)
            return None
        data['cf-turnstile-response'] = turnstile_token
        result = self.do_withdraw_generic(withdraw_url, data)
        if result and result.get('success'):
            log_success(Fore.GREEN + f"Withdraw {amount} {currency} berhasil", self.email, self.account_id)
            self.account.mark_withdraw_done(amount)
            return result
        else:
            if result and 'message' in result:
                error_msg = result['message']
                if error_msg:
                    error_lower = error_msg.lower()
                    if 'daily limit' in error_lower or 'дневной лимит' in error_lower:
                        self.withdraw_limit_reached = True
                        self.account.withdraw_limit_reached = True
                        log_warning("Withdraw limit detected, tidak akan mencoba lagi hari ini", self.email, self.account_id)
                    elif 'hourly limit' in error_lower or 'hourly withdrawal limit' in error_lower:
                        match = re.search(r'Next reset in (\d+)m (\d+)s', error_msg)
                        if match:
                            minutes = int(match.group(1))
                            seconds = int(match.group(2))
                            reset_in = minutes * 60 + seconds
                            self.hourly_cooldown = time.time() + reset_in
                            self.account.hourly_cooldown = self.hourly_cooldown
                            self.account.hourly_reset = self.hourly_cooldown
                            self.account.hourly_remaining = 0
                            log_warning(f"Hourly limit reached. Cooldown for {minutes}m {seconds}s", self.email, self.account_id)
                        else:
                            self.hourly_cooldown = time.time() + 3600
                            self.account.hourly_cooldown = self.hourly_cooldown
                            self.account.hourly_reset = self.hourly_cooldown
                            log_warning("Hourly limit reached. Could not extract reset time, cooldown 1 hour", self.email, self.account_id)
                    elif 'insufficient funds' in error_lower or 'does not have sufficient funds' in error_lower:
                        log_error("The faucet does not have sufficient funds for this transaction.", self.email, self.account_id)
            log_warning("Withdraw gagal", self.email, self.account_id)
            return result

    def withdraw_all_currencies(self, withdraw_url, form_data, amount):
        currencies = ['LTC', 'USDT', 'BTC']
        insufficient_count = 0
        for currency in currencies:
            if self.withdraw_limit_reached:
                log_info("Withdraw limit tercapai, hentikan percobaan currency lain", self.email, self.account_id)
                return False
            if self.all_empty:
                if time.time() - self.last_all_empty_time < 3600:
                    log_info("Semua currency masih dalam cooldown 1 jam, skip withdraw", self.email, self.account_id)
                    return False
                else:
                    self.all_empty = False
                    self.account.all_empty = False
            if self.hourly_cooldown is not None:
                return False
            log_info(f"Mencoba withdraw {amount} {currency}", self.email, self.account_id)
            result = self.perform_withdraw(withdraw_url, form_data, amount, currency=currency)
            if self.withdraw_limit_reached:
                log_info("Withdraw limit tercapai, hentikan percobaan currency lain", self.email, self.account_id)
                return False
            if self.hourly_cooldown is not None:
                return False
            if result and result.get('success'):
                log_success(f"Withdraw {amount} {currency} berhasil", self.email, self.account_id)
                return True
            else:
                if result and 'message' in result:
                    msg = result['message'].lower()
                    if 'insufficient funds' in msg or 'does not have sufficient funds' in msg:
                        log_warning(f"Gagal withdraw {currency}: insufficient funds", self.email, self.account_id)
                        insufficient_count += 1
                    elif 'minimum withdrawal' in msg:
                        log_warning(f"Gagal withdraw {currency} karena: {result['message']}", self.email, self.account_id)
                    else:
                        log_warning(f"Gagal withdraw {currency} karena: {result['message']}", self.email, self.account_id)
                else:
                    log_warning(f"Gagal withdraw {currency} tanpa pesan jelas", self.email, self.account_id)
        if insufficient_count == len(currencies):
            self.all_empty = True
            self.account.all_empty = True
            self.last_all_empty_time = time.time()
            self.account.last_all_empty_time = self.last_all_empty_time
            log_warning("Semua currency mengalami insufficient funds, akan jeda 1 jam sebelum coba lagi", self.email, self.account_id)
        return False

    def check_balance_and_withdraw(self, amount=None):
        if self.withdraw_limit_reached:
            log_info("Withdraw sudah limit hari ini, skip", self.email, self.account_id)
            return
        if self.all_empty:
            if time.time() - self.last_all_empty_time < 3600:
                wait_time = 3600 - (time.time() - self.last_all_empty_time)
                log_info(f"Semua currency kosong, menunggu {wait_time:.0f} detik sebelum coba lagi", self.email, self.account_id)
                time.sleep(wait_time)
                self.all_empty = False
                self.account.all_empty = False
                self._login()
            else:
                self.all_empty = False
                self.account.all_empty = False
        log_info("Cek saldo...", self.email, self.account_id)
        try:
            resp = self.http_request("GET", WITHDRAW_URL)
            if resp.status_code != 200:
                log_error("Gagal mengakses dashboard", self.email, self.account_id)
                return
            html = resp.text
        except Exception as e:
            log_error(f"Gagal mengambil dashboard: {e}", self.email, self.account_id)
            return
        balance = self.extract_balance(html)
        if balance is None:
            log_warning("Tidak dapat membaca saldo", self.email, self.account_id)
            return
        log_info(f"Saldo: {balance:.8f} LTC", self.email, self.account_id)
        hourly_info = self.extract_hourly_limit_info(html)
        if hourly_info:
            remaining_hour = hourly_info.get('remaining_this_hour')
            if remaining_hour is not None:
                log_info(f"Sisa limit per jam: {remaining_hour:.8f} LTC", self.email, self.account_id)
                if remaining_hour:
                    withdraw_amount = remaining_hour
                else:
                    log_info("Tidak ada sisa limit per jam, skip withdraw", self.email, self.account_id)
                    return
        else:
            withdraw_amount = amount if amount is not None else MIN_WITHDRAW
        if balance < withdraw_amount:
            log_info(f"Saldo < {withdraw_amount}, tidak withdraw", self.email, self.account_id)
            return
        csrf_token = self.extract_csrf_token(html)
        if not csrf_token:
            log_error("Tidak ada CSRF token di dashboard", self.email, self.account_id)
            return
        withdraw_sitekey = self.extract_sitekey(html)
        if withdraw_sitekey:
            self.withdraw_sitekey = withdraw_sitekey
            log_info(f"Sitekey withdraw berhasil diekstrak: {withdraw_sitekey}", self.email, self.account_id)
        else:
            self.withdraw_sitekey = self.SITEKEY_ROLL
            log_warning(f"Gunakan fallback sitekey withdraw: {self.withdraw_sitekey}", self.email, self.account_id)
        form_data = {'csrf_token': csrf_token, 'transaction_type': 'instant_withdraw'}
        self.withdraw_all_currencies(INSTANT_WITHDRAW_URL, form_data, withdraw_amount)

    def _login(self):
        try:
            resp = self.http_request("GET", BASE_URL1)
            if resp.status_code != 200:
                log_error("Gagal memuat halaman utama", self.email, self.account_id)
                return False
            
            html = resp.text
            email_csrf = self.extract_csrf_token(html)
            request_id = self.extract_request_id(html)
            
            if not email_csrf or not request_id:
                log_error("Tidak dapat CSRF token atau request_id", self.email, self.account_id)
                return False
            
            login_sitekey = self.extract_sitekey(html) or self.SITEKEY_LOGIN
            domain = BASE_URL.replace('https://', '').replace('http://', '')
            turnstile_token = self.solve_turnstile(domain, sitekey=login_sitekey)
            
            if not turnstile_token:
                log_error("Gagal token Turnstile", self.email, self.account_id)
                return False
            
            if not self.submit_email(email_csrf, request_id, turnstile_token):
                log_error("Submit email gagal", self.email, self.account_id)
                return False
            
            resp = self.http_request("GET", ROLL_URL)
            if resp.status_code != 200:
                log_error("Gagal memuat halaman mining", self.email, self.account_id)
                return False
            
            self.html = resp.text
            self.mine_csrf = self.extract_csrf_token(self.html)
            
            roll_sitekey = self.extract_sitekey(self.html)
            if roll_sitekey:
                self.roll_sitekey = roll_sitekey
            
            dash_resp = self.http_request("GET", WITHDRAW_URL)
            if dash_resp.status_code == 200:
                self.extract_hourly_limit_info(dash_resp.text)
                self.balance = self.extract_balance(dash_resp.text)
            
            log_success("✅ Login berhasil", self.email, self.account_id)
            return True
            
        except Exception as e:
            log_error(f"Login gagal: {e}", self.email, self.account_id)
            return False

    # ========== METHOD CLAIM BONUS DIHAPUS - TIDAK DIGUNAKAN ==========
    # def claim_bonus(self, csrf_token):  <-- DIHAPUS

    def claim_withdrawal_bonus(self):
        """Mengklaim bonus dari halaman withdrawal_bonus.php hingga 50x (LOGIKA ASLI ANDA)"""
        if self.bonus_cooldown and time.time() < self.bonus_cooldown:
            remaining = self.bonus_cooldown - time.time()
            log_info(f"Bonus cooldown aktif, sisa {remaining:.0f} detik", self.email, self.account_id)
            return

        bonus_url = f"{BASE_URL}/withdrawal_bonus.php"
        max_claims = 50
        claims_done = 0

        while claims_done < max_claims:
            log_info(f"Mencoba klaim bonus ke-{claims_done+1}/{max_claims}", self.email, self.account_id)

            try:
                resp = self.http_request("GET", bonus_url)
                if resp.status_code != 200:
                    log_error(f"Gagal memuat {bonus_url}, status {resp.status_code}", self.email, self.account_id)
                    return
                html = resp.text
            except Exception as e:
                log_error(f"Exception saat load bonus page: {e}", self.email, self.account_id)
                return

            reset_seconds = self.extract_reset_timer(html)
            csrf = self.extract_csrf_token(html)
            if not csrf:
                log_error("Tidak dapat CSRF token di halaman bonus", self.email, self.account_id)
                return

            sitekey = self.extract_sitekey(html)
            if not sitekey:
                sitekey = self.SITEKEY_LOGIN
                log_info(f"Menggunakan fallback sitekey: {sitekey}", self.email, self.account_id)

            soup = BeautifulSoup(html, 'html.parser')
            token_input = soup.find('input', {'name': 'cf-turnstile-response'})
            
            if token_input and token_input.get('value'):
                token = token_input['value']
                log_info("Token ditemukan di halaman", self.email, self.account_id)
            else:
                log_info("Mendapatkan token dari solver...", self.email, self.account_id)
                domain = bonus_url.replace('https://', '').replace('http://', '')
                token = self.solve_turnstile(domain, sitekey=sitekey)
                if not token:
                    log_error("Gagal mendapatkan token dari solver", self.email, self.account_id)
                    return

            data = {
                'action': 'add_bonus',
                'csrf_token': csrf,
                'cf-turnstile-response': token,
                'cf_turnstile_response': token
            }
            headers = {
                "X-Requested-With": "XMLHttpRequest",
                "Referer": bonus_url,
                "Content-Type": "application/x-www-form-urlencoded"
            }

            try:
                post_resp = self.http_request("POST", bonus_url, data=data, headers=headers, allow_redirects=True)
                if post_resp.status_code != 200:
                    log_error(f"HTTP {post_resp.status_code} saat klaim bonus", self.email, self.account_id)
                    return

                try:
                    j = post_resp.json()
                    if j.get('success'):
                        log_success(f"Klaim withdrawal bonus ke-{claims_done+1} berhasil!", self.email, self.account_id)
                        claims_done += 1
                        time.sleep(1)
                        continue
                    else:
                        msg = j.get('message', 'Unknown error')
                        log_warning(f"Klaim bonus gagal: {msg}", self.email, self.account_id)
                        if any(kw in msg.lower() for kw in ['hourly limit', 'daily limit', 'cooldown', 'terlalu sering', 'limit']):
                            self._set_bonus_cooldown(reset_seconds)
                        return
                except ValueError:
                    error_msg = self.extract_error_from_html(post_resp.text)
                    if error_msg:
                        log_error(f"Bonus error: {error_msg}", self.email, self.account_id)
                        if any(kw in error_msg.lower() for kw in ['hourly limit', 'daily limit', 'cooldown']):
                            self._set_bonus_cooldown(reset_seconds)
                    else:
                        if 'success' in post_resp.text.lower() or 'bonus added' in post_resp.text.lower():
                            log_success(f"Klaim withdrawal bonus ke-{claims_done+1} berhasil (HTML)", self.email, self.account_id)
                            claims_done += 1
                            time.sleep(1)
                            continue
                        else:
                            log_error("Respon bonus tidak dikenal", self.email, self.account_id)
                    return
            except Exception as e:
                log_error(f"Exception saat POST bonus: {e}", self.email, self.account_id)
                return

        if claims_done >= max_claims:
            if reset_seconds:
                self.bonus_cooldown = time.time() + reset_seconds
                self.account.bonus_cooldown = self.bonus_cooldown
                log_success(f"Berhasil melakukan 50 klaim bonus. Menunggu reset dalam {reset_seconds//60} menit {reset_seconds%60} detik.", self.email, self.account_id)
            else:
                self._set_bonus_cooldown_from_dashboard(success=True)

    def _set_bonus_cooldown(self, reset_seconds=None):
        if reset_seconds:
            self.bonus_cooldown = time.time() + reset_seconds
            self.account.bonus_cooldown = self.bonus_cooldown
            log_info(f"Bonus limit tercapai, cooldown hingga reset ({reset_seconds//60} menit {reset_seconds%60} detik).", self.email, self.account_id)
        else:
            self._set_bonus_cooldown_from_dashboard()

    def _set_bonus_cooldown_from_dashboard(self, success=False):
        try:
            resp_dash = self.http_request("GET", WITHDRAW_URL)
            if resp_dash.status_code == 200:
                html_dash = resp_dash.text
                reset_seconds = self.extract_reset_timer(html_dash)
                if reset_seconds:
                    self.bonus_cooldown = time.time() + reset_seconds
                    self.account.bonus_cooldown = self.bonus_cooldown
                    if success:
                        log_success(f"Berhasil melakukan 50 klaim bonus. Menunggu reset dalam {reset_seconds//60} menit {reset_seconds%60} detik (dari dashboard).", self.email, self.account_id)
                    else:
                        log_info(f"Bonus limit tercapai, cooldown hingga reset ({reset_seconds//60} menit {reset_seconds%60} detik) dari dashboard.", self.email, self.account_id)
                    return
        except Exception as e:
            log_warning(f"Gagal mengambil reset timer dari dashboard: {e}", self.email, self.account_id)
        cooldown_sec = time_until_next_hour()
        self.bonus_cooldown = time.time() + cooldown_sec
        self.account.bonus_cooldown = self.bonus_cooldown
        if success:
            log_success(f"Berhasil melakukan 50 klaim bonus. Menunggu hingga jam berikutnya (fallback).", self.email, self.account_id)
        else:
            log_info(f"Bonus limit tercapai, cooldown hingga jam berikutnya (fallback).", self.email, self.account_id)

    # ========== FASE BONUS 50x (FASE 1) ==========
    def run_bonus_phase(self):
        """FASE 1: HANYA claim withdrawal bonus 50x (TANPA MINING)"""
        log_info(f"🎁 FASE BONUS 50x - Akun #{self.account_id}", self.email, self.account_id)
        
        # Setup proxy
        if self.proxy_manager:
            if not self._get_new_proxy():
                log_error(f"❌ GAGAL DAPAT PROXY!", self.email, self.account_id)
                return False
        
        # Login
        if not self._login():
            return False
        
        # HANYA CLAIM WITHDRAWAL BONUS 50x (TANPA MINING)
        log_info("🚀 Memulai withdrawal bonus 50x...", self.email, self.account_id)
        self.claim_withdrawal_bonus()
        
        # Cek saldo dan withdraw setelah bonus
        self.check_balance_and_withdraw()
        
        # Tandai selesai
        self.account.mark_bonus_done()
        
        # Update account state
        self.account.withdraw_limit_reached = self.withdraw_limit_reached
        self.account.all_empty = self.all_empty
        self.account.last_all_empty_time = self.last_all_empty_time
        self.account.hourly_cooldown = self.hourly_cooldown
        self.account.bonus_cooldown = self.bonus_cooldown
        
        log_success(f"✅ Akun #{self.account_id} SELESAI FASE BONUS 50x - SIAP FASE 2!", self.email, self.account_id)
        return True
    
    # ========== FASE WITHDRAW (FASE 2) - SESUAI LOGIKA ASLI ==========
    def run_withdraw_phase(self):
        """FASE 2: Withdraw setiap jam - MENGIKUTI LOGIKA ASLI SCRIPT"""
        log_info(f"💰 FASE WITHDRAW - Akun #{self.account_id}", self.email, self.account_id)
        
        # PASTIKAN MENGGUNAKAN PROXY YANG SAMA
        if self.proxy_manager:
            if self.account.assigned_proxy:
                log_info(f"🔄 Menggunakan proxy tetap: {self.account.assigned_proxy}", self.email, self.account_id)
                self.proxy_string = self.account.assigned_proxy
                self._setup_proxy()
                self.use_proxy = True
            else:
                if not self._get_new_proxy():
                    log_error(f"❌ GAGAL DAPAT PROXY!", self.email, self.account_id)
                    return False
        
        # Login
        if not self._login():
            return False
        
        # HANYA CEK SALDO DAN WITHDRAW - SESUAI LOGIKA ASLI
        self.check_balance_and_withdraw()
        
        # Update state
        self.account.withdraw_limit_reached = self.withdraw_limit_reached
        self.account.all_empty = self.all_empty
        self.account.last_all_empty_time = self.last_all_empty_time
        self.account.hourly_cooldown = self.hourly_cooldown
        self.account.bonus_cooldown = self.bonus_cooldown
        self.account.hourly_remaining = self.hourly_remaining
        
        log_success(f"✅ Akun #{self.account_id} WITHDRAW SELESAI UNTUK JAM INI", self.email, self.account_id)
        return True

# ========== FUNGSI LOAD FILE ==========
def load_emails_from_file(filepath="emails.txt"):
    try:
        with open(filepath, 'r') as f:
            emails = [line.strip() for line in f if line.strip() and '@' in line]

        emails = shard_list(emails, WORKER_ID, WORKER_TOTAL)

        log_info(f"Worker {WORKER_ID}: mengambil {len(emails)} email")
        return emails

    except FileNotFoundError:
        return []

def load_proxies_from_file(filepath="proxies.txt"):
    try:
        with open(filepath, 'r') as f:
            proxies = [line.strip() for line in f if line.strip()]

        proxies = shard_list(proxies, WORKER_ID, WORKER_TOTAL)

        log_info(f"Worker {WORKER_ID}: mengambil {len(proxies)} proxy")
        return proxies

    except FileNotFoundError:
        return []

# ========== MONITOR PROXY FILE ==========
def check_proxy_file_changes(proxy_manager: ProxyManager):
    global last_proxy_file_mtime
    
    while True:
        try:
            if os.path.exists(PROXY_FILE):
                current_mtime = os.path.getmtime(PROXY_FILE)
                
                if current_mtime > last_proxy_file_mtime:
                    last_proxy_file_mtime = current_mtime
                    log_info(f"\n📁 File {PROXY_FILE} berubah, reloading proxy...")
                    
                    if proxy_manager.reload_from_file():
                        proxy_stats = proxy_manager.get_stats()
                        log_success(f"📦 Proxy stats: {proxy_stats['fresh']} fresh, {proxy_stats['assigned']} assigned, {proxy_stats['failed']} failed")
                        if proxy_stats['fresh'] == 0:
                            log_warning("⚠️ PERHATIAN: Tidak ada proxy FRESH! Tambahkan proxy baru di proxies.txt")
            
            time.sleep(proxy_reload_interval)
        except Exception as e:
            log_error(f"Error monitoring proxy file: {e}")
            time.sleep(proxy_reload_interval)

def handle_user_input(proxy_manager: ProxyManager, account_pool: AccountPool):
    while True:
        try:
            cmd = input().strip().lower()
            
            if cmd == "reload":
                log_info("\n🔄 Manual reload proxy...")
                if proxy_manager.reload_from_file():
                    proxy_stats = proxy_manager.get_stats()
                    log_success(f"📦 Proxy stats: {proxy_stats['fresh']} fresh, {proxy_stats['assigned']} assigned, {proxy_stats['failed']} failed")
                    if proxy_stats['fresh'] == 0:
                        log_warning("⚠️ PERHATIAN: Tidak ada proxy FRESH! Tambahkan proxy baru di proxies.txt")
                else:
                    log_warning("⚠️ Tidak ada proxy baru ditambahkan")
            
            elif cmd == "status":
                proxy_stats = proxy_manager.get_stats() if proxy_manager else None
                account_stats = account_pool.get_progress()
                
                print(f"\n{Colors.HEADER}{Colors.BOLD}=== STATUS BOT ==={Colors.ENDC}")
                print(f"{Colors.OKCYAN}⏱️ Waktu: {datetime.now().strftime('%H:%M:%S')}{Colors.ENDC}")
                print(f"{Colors.OKBLUE}📊 Total Akun: {account_stats['total']}{Colors.ENDC}")
                print(f"{Colors.OKBLUE}🎁 Bonus 50x: {account_stats['bonus_done']}/{account_stats['total']}{Colors.ENDC}")
                print(f"{Colors.OKBLUE}💰 Siap Withdraw: {account_stats['can_withdraw']}{Colors.ENDC}")
                print(f"{Colors.OKBLUE}⏳ Menunggu: {account_stats['waiting']}{Colors.ENDC}")
                print(f"{Colors.OKBLUE}📌 Fase: {account_stats['phase']}{Colors.ENDC}")
                
                if account_stats['waiting_details']:
                    print(f"\n{Colors.OKCYAN}⏳ Top 5 waiting:{Colors.ENDC}")
                    for acc_id, wait in account_stats['waiting_details']:
                        mins = int(wait // 60)
                        secs = int(wait % 60)
                        print(f"  #{acc_id}: {mins:02d}:{secs:02d}")
                
                if proxy_stats:
                    print(f"\n{Colors.OKCYAN}📦 Status Proxy:{Colors.ENDC}")
                    print(f"  {Colors.OKGREEN}✅ FRESH: {proxy_stats['fresh']}{Colors.ENDC}")
                    print(f"  {Colors.WARNING}⚠️ Assigned: {proxy_stats['assigned']}{Colors.ENDC}")
                    print(f"  {Colors.FAIL}❌ Failed: {proxy_stats['failed']}{Colors.ENDC}")
                    print(f"  {Colors.HEADER}📈 Total: {proxy_stats['total_all']}{Colors.ENDC}")
                    
                    if proxy_stats['fresh'] == 0:
                        print(f"\n{Colors.FAIL}{Colors.BOLD}⚠️ PERINGATAN KRITIS:{Colors.ENDC}")
                        print(f"{Colors.FAIL}STOK PROXY FRESH HABIS! Tambahkan proxy baru di {PROXY_FILE}!{Colors.ENDC}")
                
                print()
            
        except Exception as e:
            pass

def show_banner(account_pool: AccountPool, proxy_manager: ProxyManager):
    account_stats = account_pool.get_progress() if account_pool else {'total': 0}
    proxy_stats = proxy_manager.get_stats() if proxy_manager else {'fresh': 0, 'assigned': 0, 'failed': 0, 'total_all': 0}
    
    banner = f"""
{Colors.HEADER}{Colors.BOLD}
╔══════════════════════════════════════════════════════════════╗
║                    LITECOIN FARM BOT                         ║
║                 Multi Account + Proxy Manager                ║
║                   Dedicated Proxy per Account                ║
║              Fase 1: Bonus 50x | Fase 2: Withdraw/jam       ║
║                    TANPA MINING 10x                          ║
╚══════════════════════════════════════════════════════════════╝
{Colors.ENDC}
{Colors.OKCYAN}Starting at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{Colors.ENDC}
{Colors.OKBLUE}📊 Total Akun: {account_stats['total']}{Colors.ENDC}
{Colors.OKGREEN}✅ Proxy FRESH: {proxy_stats['fresh']}{Colors.ENDC}
{Colors.WARNING}⚠️ Assigned: {proxy_stats['assigned']}{Colors.ENDC}
{Colors.FAIL}❌ Failed: {proxy_stats['failed']}{Colors.ENDC}
{Colors.HEADER}📈 Total Proxy: {proxy_stats['total_all']}{Colors.ENDC}
{Colors.WARNING}Solver URL: {SOLVER_URL}{Colors.ENDC}
{Colors.WARNING}Ketik 'reload' untuk reload proxy, 'status' untuk statistik{Colors.ENDC}
"""
    print(banner)

def shard_list(data, worker_id, total_workers):
    if total_workers <= 1:
        return data
    return data[worker_id::total_workers]

def get_user_input():
    global SHOW_EMAIL_IN_LOOP, USE_ACCOUNT_ID
    
    print(f"\n{Colors.HEADER}{Colors.BOLD}=== LITECOIN FARM BOT - MULTI ACCOUNT ==={Colors.ENDC}")
    print(f"{Colors.WARNING}Mode: SETIAP AKUN PUNYA PROXY TETAP - TIDAK ADA REUSE{Colors.ENDC}")
    print(f"{Colors.WARNING}2 FASE: Bonus 50x → Withdraw setiap jam{Colors.ENDC}")
    print(f"{Colors.WARNING}TANPA MINING 10x - LANGSUNG BONUS 50x{Colors.ENDC}")
    print(f"{Colors.WARNING}Ketik 'reload' untuk reload manual, 'status' untuk lihat statistik{Colors.ENDC}")
    
    print(f"\n{Colors.OKBLUE}Konfigurasi Tampilan:{Colors.ENDC}")
    #show_email = input(f"Tampilkan email? (y/n, default: n): {Colors.ENDC}").strip().lower()
    #SHOW_EMAIL_IN_LOOP = show_email in ['y', 'yes']
    #SHOW_EMAIL_IN_LOOP = 'y'
    SHOW_EMAIL_IN_LOOP = True
    
    #use_id = input(f"Tampilkan ID akun? (y/n, default: y): {Colors.ENDC}").strip().lower()
    #USE_ACCOUNT_ID = use_id not in ['n', 'no']
    #USE_ACCOUNT_ID = 'y'
    USE_ACCOUNT_ID = True
    
    print(f"\n{Colors.OKBLUE}Pilih metode input email:{Colors.ENDC}")
    print("1. Manual")
    print("2. Dari file (emails.txt)")
    #choice = input("Pilihan (1/2): ").strip()
    choice = '2'
    
    emails = []
    if choice == '1':
        print(f"\n{Colors.OKCYAN}Masukkan email (kosongkan untuk selesai):{Colors.ENDC}")
        while True:
            email = input("Email: ").strip()
            if not email:
                break
            if '@' in email:
                emails.append(email)
            else:
                print(f"{Colors.FAIL}Email tidak valid!{Colors.ENDC}")
    else:
        emails = load_emails_from_file()
        if not emails:
            print(f"{Colors.FAIL}Tidak ada email dalam file{Colors.ENDC}")
            return [], []
        print(f"{Colors.OKGREEN}Loaded {len(emails)} emails{Colors.ENDC}")
    
    if not emails:
        print(f"{Colors.FAIL}Tidak ada email{Colors.ENDC}")
        return [], []
    
    print(f"\n{Colors.OKBLUE}Pilih metode input proxy:{Colors.ENDC}")
    print("1. Manual")
    print("2. Dari file (proxies.txt) - Auto-reload")
    print("3. Tidak menggunakan proxy")
    #proxy_choice = input("Pilihan (1/2/3): ").strip()
    proxy_choice = '2'
    
    proxies = []
    if proxy_choice == '1':
        print(f"\n{Colors.OKCYAN}Masukkan proxy (format host:port:user:pass atau host:port){Colors.ENDC}")
        while True:
            proxy = input("Proxy: ").strip()
            if not proxy:
                break
            parts = proxy.split(':')
            if len(parts) in [2, 4]:
                proxies.append(proxy)
            else:
                print(f"{Colors.FAIL}Format proxy salah!{Colors.ENDC}")
    elif proxy_choice == '2':
        proxies = load_proxies_from_file()
        if not proxies:
            print(f"{Colors.FAIL}Tidak ada proxy, tanpa proxy{Colors.ENDC}")
        else:
            print(f"{Colors.OKGREEN}Loaded {len(proxies)} proxies (auto-reload aktif){Colors.ENDC}")
    else:
        print(f"{Colors.WARNING}Berjalan tanpa proxy{Colors.ENDC}")
    
    return emails, proxies

def main():
    emails, proxies = get_user_input()
    
    if not emails:
        log_error("Tidak ada email")
        return
    
    account_pool = AccountPool(emails)
    proxy_manager = ProxyManager(proxies) if proxies else None
    
    global last_proxy_file_mtime
    if os.path.exists(PROXY_FILE):
        last_proxy_file_mtime = os.path.getmtime(PROXY_FILE)
    
    show_banner(account_pool, proxy_manager)
    
    if proxy_manager:
        monitor_thread = threading.Thread(target=check_proxy_file_changes, args=(proxy_manager,), daemon=True)
        monitor_thread.start()
    
    input_thread = threading.Thread(target=handle_user_input, args=(proxy_manager, account_pool), daemon=True)
    input_thread.start()
    
    loop_count = 0
    start_time = time.time()
    
    try:
        while True:
            loop_count += 1
            result = account_pool.get_next_account()
            
            if not result:
                time.sleep(10)
                continue
            
            account, action = result
            
            log_info(f"\n{'='*60}")
            log_info(f"[FASE: {account_pool.current_phase}] Loop #{loop_count}")
            log_info(f"Memproses akun #{account.account_id}: {account.email} - Mode: {action}")
            
            if action == "WITHDRAW" and account.hourly_remaining > 0:
                log_info(f"💰 Sisa limit per jam: {account.hourly_remaining:.8f} LTC")
            
            bot = LitecoinFarmBot(account, proxy_manager)
            
            if action == "BONUS":
                result = bot.run_bonus_phase()
            else:
                result = bot.run_withdraw_phase()
            
            stats = account_pool.get_progress()
            elapsed = time.time() - start_time
            hours = elapsed // 3600
            minutes = (elapsed % 3600) // 60
            
            log_info(f"Progress Bonus: {stats['bonus_done']}/{stats['total']} | Siap Withdraw: {stats['can_withdraw']} | Menunggu: {stats['waiting']}")
            log_info(f"Runtime: {int(hours)}j {int(minutes)}m | Fase: {stats['phase']}")
            
            time.sleep(random.uniform(5, 10))
    
    except KeyboardInterrupt:
        log_info("\n\n" + "="*60)
        log_info("🛑 Program dihentikan oleh user")
        
        total_time = time.time() - start_time
        hours = total_time // 3600
        minutes = (total_time % 3600) // 60
        
        print(f"\n{Colors.HEADER}{Colors.BOLD}=== RINGKASAN ==={Colors.ENDC}")
        print(f"{Colors.OKCYAN}⏱️ Runtime: {int(hours)}j {int(minutes)}m{Colors.ENDC}")
        print(f"{Colors.OKGREEN}🔄 Total loops: {loop_count}{Colors.ENDC}")
        
        sys.exit(0)

if __name__ == "__main__":
    main()