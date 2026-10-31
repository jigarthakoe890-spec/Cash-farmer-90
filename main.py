"""
કેશ ફાર્મર સર્વર (Flask)

બધી ચાવીઓ (કી), ડેટાબેઝની ઓળખ અને બેલેન્સનો હિસાબ આ સર્વર પર જ રહે છે.
HTML ફાઈલો ફક્ત આ સર્વરના /api/... રસ્તા બોલાવે છે.

ચલાવવા માટે:
    pip install -r requirements.txt
    python app.py
પછી બ્રાઉઝરમાં http://127.0.0.1:5000 ખોલો.
"""
import json
import hmac
import logging
import math
import os
import queue
import random
import re
import string
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from functools import wraps

import requests
from flask import Flask, Response, g, jsonify, request, send_from_directory
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.exceptions import NotFound
from werkzeug.security import check_password_hash, generate_password_hash

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("cashfarmer")


# ----------------------------------------------------------------------------
# ગુપ્ત સેટિંગ: બધી કી અને ID અહીં જ લખો
# (આ ફાઈલ `public` ફોલ્ડરમાં નથી, એટલે વપરાશકર્તા તેને જોઈ શકતો નથી.
#  પણ આ ફાઈલ કોઈને મોકલશો નહીં અને ગિટહબ/ટેલિગ્રામ પર મૂકશો નહીં.)
# ----------------------------------------------------------------------------
APPWRITE_ENDPOINT = "https://fra.cloud.appwrite.io/v1"
APPWRITE_PROJECT_ID = "6985aa6e0018fb6d3ef8"
APPWRITE_DATABASE_ID = "6a0c59ac002413005872"

# એપરાઈટ કન્સોલ > Overview > API keys માં નવી કી બનાવો (પરવાનગી: documents.read અને documents.write)
APPWRITE_API_KEY = "standard_8e05de023d2eeebe5292137816c5f400e6a1749ff3b4594b9e42cab0407ae31cacbe197bb1b262b481a78fcbe7bcf187b86e5d2e37a3e827fd045604f4d39e5722bb6d529a259c8a43b52e16f38699d2377d055fa96b3498aef572c3e65d85350411d5a5418644d0aca4d8fff769046e87ea9d5397c1793ce11bf28e215f4ba4"

# ImgBB ની નવી કી (જૂની કી રદ કરો)
IMGBB_API_KEY = "8c5b5ce8657dbaa910dc1d2f2a1feef2"

# લોગિન ટોકન સાચા છે કે નકલી તે ચકાસવા માટેનું ગુપ્ત લખાણ (મેં બનાવી આપ્યું છે, બદલવું જરૂરી નથી)
SECRET_KEY = "1cee97246f1da3872c21ce3601ae4706aa484f93bb5ad6ec8d21ba0e616d4dc9"

# એડમિન પેનલ સર્વરને "આ યુઝરનો ડેટા તાજો કરો" કહેવા માટેનો ગુપ્ત શબ્દ.
# અહીં કોઈ લાંબો, અઘરો શબ્દ લખો (અથવા Render ના સેટિંગમાં ADMIN_SECRET નામથી મૂકો).
# ખાલી રાખશો તો આ સુવિધા બંધ રહેશે. આ શબ્દ કોઈ સાથે વહેંચવો નહીં.
ADMIN_SECRET = "Gnn9hcF2xwr_YjGz8PkFyLjPDnN7tw0q"

# HTML બીજી એપ (જેમ કે Spck Editor) માંથી ચાલતી હોય ત્યારે તેને સર્વર વાપરવા દેવા માટે.
# ટેસ્ટ માટે "*" ચાલશે. ઓનલાઈન મૂકો ત્યારે તમારી સાઈટનું સાચું સરનામું લખજો, જેમ કે "https://mysite.com"
CORS_ORIGIN = "*"

# HTML ફાઈલો (index.html, loginpage.html) અને ચિત્રો જે ફોલ્ડરમાં રાખ્યા હોય તેનું પૂરું સરનામું અહીં લખો.
# દા.ત. "/storage/emulated/0/Download/public"   ખાલી રાખશો તો સર્વર જાતે શોધશે.
PUBLIC_FOLDER = ""

# રેફરલ લિંકની શરૂઆત. લિંક = આ + રેફર કોડ. HTML આ જ લિંક સર્વર પાસેથી લે છે (બીજે ક્યાંય લખેલી નથી).
INVITE_BASE = "https://cashfaremer.netlify.app/inviteRefer/CFKJSLTK="

# ઓનલાઈન હોસ્ટિંગમાં આ કિંમતો તેમની સાઈટના સેટિંગમાં પણ આપી શકાય, તે અહીંની કિંમત કરતાં આગળ ગણાશે.
ENDPOINT = (os.environ.get("APPWRITE_ENDPOINT") or APPWRITE_ENDPOINT).rstrip("/")
PROJECT_ID = os.environ.get("APPWRITE_PROJECT_ID") or APPWRITE_PROJECT_ID
DATABASE_ID = os.environ.get("APPWRITE_DATABASE_ID") or APPWRITE_DATABASE_ID
API_KEY = (os.environ.get("APPWRITE_API_KEY") or APPWRITE_API_KEY).strip()
IMGBB_KEY = (os.environ.get("IMGBB_API_KEY") or IMGBB_API_KEY).strip()
SECRET_KEY = os.environ.get("SECRET_KEY") or SECRET_KEY
ADMIN_SECRET = (os.environ.get("ADMIN_SECRET") or ADMIN_SECRET).strip()
CORS_ORIGIN = os.environ.get("CORS_ORIGIN") or CORS_ORIGIN
INVITE_BASE = os.environ.get("INVITE_BASE") or INVITE_BASE

if not API_KEY:
    raise SystemExit("app.py ની ઉપર APPWRITE_API_KEY માં એપરાઈટની નવી કી લખો")

# ટેબલ (collection) ના નામ
C_USERS = "user_information"
C_TASKS = "user_task_approval"
C_WITHDRAW = "withdraw_request"
C_HISTORY = "user_reward_history"
C_OFFERS = "offer_list"

# ઉપાડની મર્યાદા અને ફી (બધા નિયમ ફક્ત અહીં જ, HTML કંઈ ગણતું નથી)
MIN_WITHDRAW = 5
MAX_WITHDRAW = 999
FEE_PERCENT = 2        # ફી ૨%
FEE_FREE_BELOW = 30    # આટલાથી ઓછી રકમ પર ફી નથી, આટલી કે તેથી વધુ પર ફી લાગે

# રેફરલ ઇનામ (લેવલ પ્રમાણે) અને જરૂરી ટાસ્ક (મિત્રના અલગ અલગ ઓફર મંજૂર થયા હોય)
REFER_REWARDS = {1: 40, 2: 5, 3: 2}
REFER_MIN_PRIZE = 40       # [નવું] રેફર ગણતરીમાં ફક્ત આટલા કે તેથી વધુ ઇનામ વાળા ટાસ્ક ગણાય (૩૯ કે ઓછા નહીં)
REFER_TASKS_NEEDED = 2   # [બદલ્યું: ૩ → ૨] ટેલિગ્રામ સિવાયના ૨ અલગ ટાસ્ક મંજૂર થાય ત્યારે રેફર ઇનામ
REFER_CHECK_SECONDS = 1800  # બધાને તપાસતું ધીમું ચક્ર (હમણાં બંધ છે, નીચે NO_BACKGROUND જુઓ)
# [નવું] રેફર યાદી (મિત્રો, લેવલ, સફળ રેફર) સર્વરની યાદમાં આટલા સેકન્ડ સુધી રહે (૧૨ કલાક).
# સાઇનઅપ અને બોનસ વખતે યાદ સીધી બદલાય છે, એટલે ડેટાબેઝ ફરી વાંચવો પડતો નથી.
# આ ફક્ત સલામતી માટે છે (કન્સોલમાં સીધા ફેરફાર થયા હોય તો ક્યારેક સુધરી જાય).
REFER_MEM_SECONDS = 43200
REFER_MEM_MAX_USERS = 500     # એક સાથે વધુમાં વધુ આટલા રેફર કરનારની યાદી યાદમાં રહે
OFFERS_CACHE_SECONDS = 21600  # ઓફરોની યાદી સર્વર આટલા સેકન્ડ (૬ કલાક) યાદ રાખે (reads બચાવવા). નવી ઓફર તરત બતાવવી હોય તો સર્વર ફરી ચાલુ કરો
USER_CACHE_SECONDS = 1800  # વપરાશકર્તાના ટાસ્ક અને ઇતિહાસની યાદી સર્વર આટલા સેકન્ડ (૩૦ મિનિટ) યાદ રાખે (ફક્ત સ્ક્રીન બતાવવા માટે)
AUTH_CACHE_SECONDS = 1800  # લોગિન ચકાસવા અને બેલેન્સ બતાવવા માટે યુઝરની રો સર્વર આટલા સેકન્ડ (૩૦ મિનિટ) યાદ રાખે
STATS_SYNC_MIN_SECONDS = 300  # એક વપરાશકર્તાના આંકડા /api/sync-stats થી આટલા સેકન્ડે એક જ વાર ગણાય

# તરત સંદેશ મોકલવાનું ખુલ્લું જોડાણ (/api/stream) - ટાસ્ક મંજૂર કે રેફર ઇનામ મળે ત્યારે એપમાં તરત દેખાય
STREAM_MAX_SECONDS = 900      # એક જોડાણ વધુમાં વધુ ૧૫ મિનિટ ચાલે, પછી એપ આપોઆપ ફરી જોડાય
STREAM_PING_SECONDS = 25      # જોડાણ જીવતું રાખવા દર ૨૫ સેકન્ડે નાનો સંકેત
MAX_STREAMS_TOTAL = 300       # એક સાથે વધુમાં વધુ આટલા યુઝરનાં ખુલ્લાં જોડાણ (સર્વર પર ભાર ન પડે)
MAX_STREAMS_PER_USER = 2      # એક યુઝરનાં વધુમાં વધુ આટલાં જોડાણ
HISTORY_PUSH_LIMIT = 7        # HTML ના HISTORY_PAGE_SIZE જેટલું (ઇતિહાસનું પહેલું પાનું)

# ઉપાડ સ્ક્રીનના ઝડપી રકમ બટન
QUICK_AMOUNTS = [5, 10, 499]

TOKEN_MAX_AGE = 30 * 24 * 3600  # લોગિન ૩૦ દિવસ ચાલે
MAX_PHOTOS = 4
MAX_PHOTO_BYTES = 8 * 1024 * 1024


def find_public_dir():
    if PUBLIC_FOLDER.strip():
        return PUBLIC_FOLDER.strip()
    here = os.path.dirname(os.path.abspath(__file__))
    for base in (here, os.getcwd()):
        for cand in (os.path.join(base, "public"), base):
            if os.path.isfile(os.path.join(cand, "index.html")):
                return cand
    return os.path.join(here, "public")


PUBLIC_DIR = find_public_dir()

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024
serializer = URLSafeTimedSerializer(SECRET_KEY, salt="cashfarmer-auth")


# ----------------------------------------------------------------------------
# એપરાઈટ (REST) સાથે વાત કરવાના સાધનો
# ----------------------------------------------------------------------------
class AppwriteError(Exception):
    def __init__(self, message, status=500):
        super().__init__(message)
        self.status = status


_http = requests.Session()
_AW_HEADERS = {
    "X-Appwrite-Project": PROJECT_ID,
    "X-Appwrite-Key": API_KEY,
    "Content-Type": "application/json",
}


def _call(method, path, **kwargs):
    url = f"{ENDPOINT}/databases/{DATABASE_ID}{path}"
    try:
        r = _http.request(method, url, headers=_AW_HEADERS, timeout=25, **kwargs)
    except requests.RequestException as e:
        raise AppwriteError(f"network error: {e.__class__.__name__}", 503)
    if r.status_code >= 400:
        raise AppwriteError(f"{r.status_code}: {r.text[:300]}", r.status_code)
    return r.json() if r.text else {}


def q(method, attribute=None, values=None):
    d = {"method": method}
    if attribute is not None:
        d["attribute"] = attribute
    if values is not None:
        d["values"] = values
    return json.dumps(d)


def list_docs(col, queries=None, page=1000):
    out, cursor = [], None
    while True:
        qs = list(queries or []) + [q("limit", values=[page])]
        if cursor:
            qs.append(q("cursorAfter", values=[cursor]))
        docs = _call("GET", f"/collections/{col}/documents", params={"queries[]": qs}).get("documents", [])
        out.extend(docs)
        if len(docs) < page:
            return out
        cursor = docs[-1]["$id"]


def find_one(col, attribute, value):
    qs = [q("equal", attribute, [value]), q("limit", values=[1])]
    docs = _call("GET", f"/collections/{col}/documents", params={"queries[]": qs}).get("documents", [])
    return docs[0] if docs else None


def get_doc(col, doc_id):
    return _call("GET", f"/collections/{col}/documents/{doc_id}")


def create_doc(col, data, doc_id="unique()"):
    return _call("POST", f"/collections/{col}/documents", json={"documentId": doc_id, "data": data})


_auth_cache = {}        # યુઝર id -> (સમય, રો)
_auth_dropped = {}      # યુઝર id -> છેલ્લે ક્યારે ભૂંસ્યું
_aux_lock = threading.Lock()


def drop_user_caches(uid):
    """યુઝરની રોમાં કંઈ પણ લખાય ત્યારે તેનું યાદ રાખેલું (રો) તરત ભૂંસો."""
    now = time.time()
    with _aux_lock:
        _auth_cache.pop(uid, None)
        _auth_dropped[uid] = now


def put_user_cache(uid, doc):
    """યુઝરની રોમાં લખ્યા પછી એપરાઈટ જે તાજી રો પાછી આપે તે જ યાદમાં મૂકો, એટલે ફરી વાંચવું ન પડે."""
    if not isinstance(doc, dict) or doc.get("$id") != uid:
        return
    now = time.time()
    with _aux_lock:
        if len(_auth_cache) > 2000:
            cutoff = now - AUTH_CACHE_SECONDS
            for k in [k for k, v in _auth_cache.items() if v[0] < cutoff]:
                _auth_cache.pop(k, None)
        _auth_cache[uid] = (now, doc)


def update_doc(col, doc_id, data):
    res = _call("PATCH", f"/collections/{col}/documents/{doc_id}", json={"data": data})
    if col == C_USERS:
        drop_user_caches(doc_id)
        put_user_cache(doc_id, res)  # તાજી રો સીધી યાદમાં
    return res


def pick(doc, keys):
    return {k: doc.get(k) for k in keys if k in doc}


# ----------------------------------------------------------------------------
# તરત સંદેશ: ખુલ્લી એપને સર્વર પોતે જ નવી રકમ, ટાસ્કની સ્થિતિ અને ઇતિહાસ મોકલે છે
# ----------------------------------------------------------------------------
_streams = {}   # યુઝર id -> [queue, queue, ...]
_stream_lock = threading.Lock()


def push_user(uid, payload):
    """યુઝરની એપ ખુલ્લી (જોડાયેલી) હોય તો તેને તરત સંદેશ મોકલે. ન હોય તો કશું થતું નથી
    (યાદ તો પહેલેથી તાજી થઈ ગઈ છે, એપ ખુલે ત્યારે સાચો ડેટા જ મળશે)."""
    with _stream_lock:
        qs = list(_streams.get(uid, ()))
    for qu in qs:
        try:
            qu.put_nowait(payload)
        except queue.Full:
            pass
    return bool(qs)


def user_is_connected(uid):
    with _stream_lock:
        return bool(_streams.get(uid))


def user_push_basics(u):
    """બેલેન્સ અને રેફરના આંકડા (/api/me જેવા જ)."""
    return {
        "balance": round(float(u.get("total_balance_available") or 0), 2),
        "referNumber": u.get("user_refer_number") or 0,
        "referEarning": u.get("user_refer_earning") or 0,
    }


# ----------------------------------------------------------------------------
# નાના સાધનો
# ----------------------------------------------------------------------------
def err(message, status=400):
    return jsonify({"error": message}), status


def ist_now():
    """ભારતીય સમય (સર્વર ક્યાંય પણ હોય)"""
    return datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)


def time_date_str(d):
    h = d.hour % 12 or 12
    ampm = "PM" if d.hour >= 12 else "AM"
    return f"{h}:{d.minute:02d} {ampm} date {d.day:02d}/{d.month:02d}/{d.year}"


def parse_iso(s):
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        # એડમિન પેનલ ટાઇમઝોન વગરનો ભારતીય સમય લખે છે, એટલે તેને UTC નહીં પણ ભારતીય (+૫:૩૦) ગણવો
        return d if d.tzinfo else d.replace(tzinfo=timezone(timedelta(hours=5, minutes=30)))
    except ValueError:
        return None


def clean_nickname(raw):
    """નામમાંથી ખતરનાક અક્ષરો (< > & " ' ` \\) અને છૂપા કંટ્રોલ અક્ષરો કાઢી નાખે છે."""
    text = re.sub(r"[<>&\"'`\\\x00-\x1f\x7f]", "", str(raw or ""))
    return re.sub(r"\s+", " ", text).strip()[:50]


def safe_int(v):
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def int_if_whole(v):
    return int(v) if float(v) == int(v) else v


def norm(s):
    return str(s or "").lower().strip()


def counts_for_refer(offer_name, prize=None):
    """[નવું] રેફર ઇનામની ગણતરીમાં ફક્ત એવા ટાસ્ક ગણાય જેનું ઇનામ REFER_MIN_PRIZE (૪૦) કે તેથી વધુ હોય.
    ટેલિગ્રામ ટાસ્ક ક્યારેય ગણાતો નથી. prize ન મળે (કે ૦ હોય) તો ઓફર યાદીમાંથી ઇનામ લેવાય છે."""
    if norm(offer_name) == norm(TELEGRAM_TASK_NAME):
        return False
    try:
        pr = float(prize or 0)
    except (TypeError, ValueError):
        pr = 0.0
    if pr <= 0:
        try:
            for o in cached_offers():
                if norm(o.get("taskName")) == norm(offer_name):
                    pr = float(o.get("offer_prize") or 0)
                    break
        except Exception:  # noqa
            pr = 0.0
    return pr >= REFER_MIN_PRIZE


_user_locks = defaultdict(threading.Lock)
_signup_lock = threading.Lock()


def user_lock(user_id):
    return _user_locks[user_id]


# લોગિનમાં વારંવાર ખોટો પાસવર્ડ નાખનારને રોકવા
_failed = defaultdict(list)


def too_many_failures(key):
    now = time.time()
    _failed[key] = [t for t in _failed[key] if now - t < 600]
    return len(_failed[key]) >= 10


# ----------------------------------------------------------------------------
# પાસવર્ડ અને લોગિન ટોકન
# ----------------------------------------------------------------------------
def is_hashed(stored):
    return stored.startswith(("pbkdf2:", "scrypt:"))


def verify_password(user, given):
    """નવા ખાતામાં પાસવર્ડ જેવો લખ્યો તેવો જ સચવાય છે, તેથી સીધો સરખાવાય છે.
    જૂના ખાતામાં લાંબો કોડેડ પાસવર્ડ હોય તો વપરાશકર્તાએ લખેલો પાસવર્ડ તેની સાથે સરખાવાય છે
    અને મેળ ખાય તો જ લોગિન મળે. ડેટાબેઝમાં કંઈ બદલાતું નથી."""
    stored = str(user.get("user_password") or "")
    if not stored:
        return False
    if is_hashed(stored):
        return check_password_hash(stored, given)
    return hmac.compare_digest(stored.encode("utf-8"), given.encode("utf-8"))


def make_token(user):
    return serializer.dumps({"id": user["$id"], "email": user["user_gmail_account"]})


def get_user_for_auth(uid):
    """યુઝરની રો થોડી વાર યાદ રાખે. કોઈ ફેરફાર લખાય ત્યારે આપોઆપ ભૂંસાય છે."""
    started = time.time()
    with _aux_lock:
        hit = _auth_cache.get(uid)
    if hit and started - hit[0] < AUTH_CACHE_SECONDS:
        return dict(hit[1])
    doc = get_doc(C_USERS, uid)
    with _aux_lock:
        if _auth_dropped.get(uid, 0) < started:  # લોડ ચાલતો હતો ત્યારે ફેરફાર લખાયો હોય તો જૂનું ન સાચવવું
            if len(_auth_cache) > 2000:
                cutoff = started - AUTH_CACHE_SECONDS
                for k in [k for k, v in _auth_cache.items() if v[0] < cutoff]:
                    _auth_cache.pop(k, None)
            _auth_cache[uid] = (started, doc)
    return dict(doc)


def auth_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return err("Please login first", 401)
        try:
            data = serializer.loads(header[7:], max_age=TOKEN_MAX_AGE)
        except (BadSignature, SignatureExpired):
            return err("Session expired. Please login again", 401)
        try:
            user = get_user_for_auth(data["id"])
        except AppwriteError as e:
            if e.status == 404:
                return err("Account not found", 401)
            raise
        if user.get("user_gmail_account") != data["email"]:
            return err("Please login again", 401)
        g.user = user
        return fn(*args, **kwargs)

    return wrapper


# ----------------------------------------------------------------------------
# ટાસ્કની સ્થિતિ અને આંકડા
# ----------------------------------------------------------------------------
def classify_task_status(raw):
    st = norm(raw) or "review"
    if "pending" in st:
        return "review"
    if "success" in st or "complete" in st:
        return "completed"
    if "reject" in st or "fail" in st:
        return "rejected"
    return st


def effective_status(doc):
    """ચેતવણી ૫ કલાક પછી અને નામંજૂર ૪૮ કલાક પછી ફરી ખુલે છે."""
    if not doc:
        return "unstarted"
    st = classify_task_status(doc.get("task_status"))
    now = datetime.now(timezone.utc)
    if st == "rejected" and not doc.get("is_permanent_reject") and safe_int(doc.get("reject_count")) < 3:
        t = parse_iso(doc.get("reject_time"))
        if t and now >= t + timedelta(hours=48):
            return "unstarted"
    if st == "warning" and not doc.get("is_permanent_warning"):
        t = parse_iso(doc.get("warning_time"))
        if t and now >= t + timedelta(hours=5):
            return "unstarted"
    return st


def latest_by_offer(task_docs):
    latest = {}
    for d in sorted(task_docs, key=lambda x: x.get("$createdAt", ""), reverse=True):
        latest.setdefault(norm(d.get("offer_taskname")), d)
    return latest


def compute_stats(offers, task_docs, history_rows):
    latest = latest_by_offer(task_docs)
    total = complete = reject = pending = 0
    for o in offers:
        st = effective_status(latest.get(norm(o.get("taskName"))))
        if st != "unstarted":
            total += 1
        if st == "completed":
            complete += 1
        elif st == "rejected":
            reject += 1
        elif st == "review":
            pending += 1
    w_total = w_ok = w_rej = w_pend = 0
    for h in history_rows:
        if h.get("type") != "withdraw":
            continue
        w_total += 1
        s = norm(h.get("status"))
        if "success" in s or "complete" in s:
            w_ok += 1
        elif "reject" in s or "fail" in s:
            w_rej += 1
        else:
            w_pend += 1
    return {
        "user_complete_task": complete,
        "user_pending_task": pending,
        "user_rejected_task": reject,
        "user_total_task": total,
        "user_total_withdraw": w_total,
        "user_total_successwithdraw": w_ok,
        "user_total_rejectedwithdraw": w_rej,
        "user_total_pendingwithdraw": w_pend,
    }


def user_tasks(email):
    return list_docs(C_TASKS, [q("equal", "user_gmail_account", [email]), q("orderDesc", "$createdAt")])


def user_history(email):
    return list_docs(C_HISTORY, [q("equal", "user_gmail_account", [email])])


def user_history_page(email, limit, offset):
    """ઇતિહાસનું ફક્ત એક પાનું (નવી નોંધ પહેલાં). બધી નોંધ એકસાથે વાંચતું નથી."""
    qs = [q("equal", "user_gmail_account", [email]), q("orderDesc", "$createdAt"),
          q("limit", values=[limit]), q("offset", values=[offset])]
    res = _call("GET", f"/collections/{C_HISTORY}/documents", params={"queries[]": qs})
    docs = res.get("documents", [])
    total = res.get("total")
    if isinstance(total, int):
        has_more = offset + len(docs) < total
    else:
        has_more = len(docs) >= limit
    return {"docs": docs, "hasMore": has_more, "limit": limit}


_offers_cache = {"time": 0.0, "docs": None}
_offers_lock = threading.Lock()


def cached_offers():
    """ઓફરોની યાદી બધા માટે સરખી છે અને ભાગ્યે જ બદલાય છે, એટલે થોડી વાર યાદ રાખીએ."""
    with _offers_lock:
        docs, t = _offers_cache["docs"], _offers_cache["time"]
    if docs is not None and time.time() - t < OFFERS_CACHE_SECONDS:
        return docs
    try:
        fresh = list_docs(C_OFFERS)
    except AppwriteError:
        if docs is not None:
            return docs  # એપરાઈટ ન મળે તો જૂની યાદી ચાલશે
        raise
    with _offers_lock:
        _offers_cache["docs"], _offers_cache["time"] = fresh, time.time()
    return fresh


_user_cache = {}        # (પ્રકાર, ઇમેઇલ) -> (સમય, યાદી)
_user_cache_dropped = {}  # (પ્રકાર, ઇમેઇલ) -> છેલ્લે ક્યારે ભૂંસ્યું
_user_cache_lock = threading.Lock()


def cached_user_list(kind, email, loader):
    """ફક્ત સ્ક્રીન બતાવવા માટે. ઉપાડ, ઇનામ અને ટાસ્ક મોકલવાના કામ આનો ઉપયોગ કરતા નથી."""
    key = (kind, email)
    started = time.time()
    with _user_cache_lock:
        hit = _user_cache.get(key)
    if hit and started - hit[0] < USER_CACHE_SECONDS:
        return hit[1]
    docs = loader(email)
    with _user_cache_lock:
        if _user_cache_dropped.get(key, 0) < started:  # લોડ ચાલતો હતો ત્યારે ભૂંસાયું હોય તો જૂનું ન સાચવવું
            if len(_user_cache) > 2000:
                cutoff = started - USER_CACHE_SECONDS
                for k in [k for k, v in _user_cache.items() if v[0] < cutoff]:
                    _user_cache.pop(k, None)
            _user_cache[key] = (started, docs)
    return docs


def forget_user_cache(email, *kinds):
    """વપરાશકર્તા પોતે કંઈ કરે (ઉપાડ, ટાસ્ક મોકલવો, ઇનામ મળવું) ત્યારે યાદ રાખેલું તરત ભૂંસો."""
    now = time.time()
    with _user_cache_lock:
        for kind in (kinds or ("tasks", "history")):
            _user_cache.pop((kind, email), None)
            _user_cache_dropped[(kind, email)] = now
            if kind == "history":  # પાનાં પ્રમાણે યાદ રાખેલી પહેલી યાદી પણ ભૂંસો
                _user_cache.pop(("history_p1", email), None)
                _user_cache_dropped[("history_p1", email)] = now


def cache_replace_task(email, doc):
    """ટાસ્ક બદલાય કે નવો બને ત્યારે યાદ રાખેલી યાદી ભૂંસવાને બદલે તેમાં જ તે ટાસ્ક બદલી નાખો.
    યાદ ખાલી હોય તો કશું નથી કરવાનું (એપ ખુલે ત્યારે તાજું જ વંચાશે)."""
    key = ("tasks", email)
    now = time.time()
    with _user_cache_lock:
        hit = _user_cache.get(key)
        if hit is not None and isinstance(hit[1], list):
            same = [d for d in hit[1] if d.get("$id") == doc.get("$id")]
            if same:
                lst = [doc if d.get("$id") == doc.get("$id") else d for d in hit[1]]
            else:
                lst = [doc] + list(hit[1])
            _user_cache[key] = (hit[0], lst)
        _user_cache_dropped[key] = now
    return hit is not None


def cache_set_history_status(email, entry_id, status):
    """ઇતિહાસની એક નોંધની સ્થિતિ (success/rejected) યાદમાં જ બદલો, ડેટાબેઝ ફરી વાંચ્યા વગર."""
    now = time.time()

    def fix(d):
        if d.get("entry_id") == entry_id or d.get("$id") == entry_id:
            nd = dict(d)
            nd["status"] = status
            return nd
        return d

    with _user_cache_lock:
        full = _user_cache.get(("history", email))
        if full is not None and isinstance(full[1], list):
            _user_cache[("history", email)] = (full[0], [fix(d) for d in full[1]])
        p1 = _user_cache.get(("history_p1", email))
        if p1 is not None and isinstance(p1[1], dict):
            page = dict(p1[1])
            page["docs"] = [fix(d) for d in page.get("docs", [])]
            _user_cache[("history_p1", email)] = (p1[0], page)
        _user_cache_dropped[("history", email)] = now
        _user_cache_dropped[("history_p1", email)] = now


def cache_add_history(email, doc):
    """નવી ઇતિહાસ નોંધ આવે ત્યારે યાદ રાખેલી યાદીની ટોચ પર સીધી ઉમેરો (ફરી વાંચવું નહીં)."""
    now = time.time()
    with _user_cache_lock:
        full = _user_cache.get(("history", email))
        if full is not None and isinstance(full[1], list):
            if not any(d.get("$id") == doc.get("$id") for d in full[1]):
                _user_cache[("history", email)] = (full[0], [doc] + list(full[1]))
        p1 = _user_cache.get(("history_p1", email))
        if p1 is not None and isinstance(p1[1], dict):
            page = p1[1]
            docs = list(page.get("docs", []))
            if not any(d.get("$id") == doc.get("$id") for d in docs):
                limit = page.get("limit") or (len(docs) + 1)
                new_docs = [doc] + docs
                has_more = bool(page.get("hasMore"))
                if len(new_docs) > limit:
                    new_docs = new_docs[:limit]
                    has_more = True
                _user_cache[("history_p1", email)] = (p1[0], {"docs": new_docs, "hasMore": has_more, "limit": page.get("limit")})
        _user_cache_dropped[("history", email)] = now
        _user_cache_dropped[("history_p1", email)] = now


_last_stats_sync = {}
_last_fresh_history = {}  # યુઝર id -> છેલ્લે ક્યારે તાજો ઇતિહાસ માંગ્યો (વારંવાર માંગે તો રોકવા)


def refresh_user_stats(user, fresh=True):
    """ભૂલ થાય તો મુખ્ય કામ અટકાવતું નથી. આંકડા બદલાયા ન હોય તો કશું લખાતું નથી."""
    try:
        email = user["user_gmail_account"]
        if fresh:
            tasks_docs, history_rows = user_tasks(email), user_history(email)
        else:
            tasks_docs = cached_user_list("tasks", email, user_tasks)
            history_rows = cached_user_list("history", email, user_history)
        stats = compute_stats(cached_offers(), tasks_docs, history_rows)
        if all(user.get(k) == v for k, v in stats.items()):
            return
        update_doc(C_USERS, user["$id"], stats)
    except Exception as e:  # noqa
        log.warning("આંકડા અપડેટ ન થયા: %s", e)


def save_user_stats(user, new_stats):
    """આંકડા બદલાયા હોય તો જ યુઝરની એક રોમાં લખે. કોઈ વાંચન નહીં. ભૂલ થાય તો મુખ્ય કામ અટકતું નથી."""
    try:
        if all(user.get(k) == v for k, v in new_stats.items()):
            return
        update_doc(C_USERS, user["$id"], new_stats)
    except Exception as e:  # noqa
        log.warning("આંકડા અપડેટ ન થયા: %s", e)


def refresh_task_stats_from_cache(user):
    """ટાસ્કના આંકડા ફક્ત પહેલેથી યાદ રાખેલી યાદી પરથી ગણે છે. ડેટાબેઝમાંથી કશું નવું વંચાતું નથી."""
    try:
        with _user_cache_lock:
            hit = _user_cache.get(("tasks", user["user_gmail_account"]))
        with _offers_lock:
            offers = _offers_cache["docs"]
        if not hit or offers is None or time.time() - hit[0] >= USER_CACHE_SECONDS:
            return
        stats = compute_stats(offers, hit[1], [])
        save_user_stats(user, {k: stats[k] for k in (
            "user_complete_task", "user_pending_task", "user_rejected_task", "user_total_task")})
    except Exception as e:  # noqa
        log.warning("આંકડા અપડેટ ન થયા: %s", e)


# ----------------------------------------------------------------------------
# રેફરલ કોડ અને "કોડ -> યુઝર" ની યાદ
# ----------------------------------------------------------------------------
def generate_refer_code():
    caps, smalls, nums = string.ascii_uppercase, string.ascii_lowercase, string.digits
    return random.choice(caps) + random.choice(caps) + random.choice(smalls) + random.choice(nums) + random.choice(smalls)


# [નવું] રેફર કોડ -> (યુઝર id, તેને રેફર કરનારનો કોડ). આ કદી બદલાતું નથી, એટલે કાયમ યાદ રાખી શકાય.
# ઇનામ આપતી વખતે ઉપરના લેવલ શોધવા દર વખતે ડેટાબેઝ વાંચવો પડતો નથી.
_code_info = {}
_code_info_lock = threading.Lock()


def code_info_put(code, uid, referred_by):
    if not code or not uid:
        return
    with _code_info_lock:
        if len(_code_info) > 20000:
            _code_info.clear()
        _code_info[code] = (uid, referred_by or "")


def code_info(code):
    with _code_info_lock:
        hit = _code_info.get(code)
    if hit:
        return hit
    doc = find_one(C_USERS, "user_refer_code", code)
    if not doc:
        return None
    code_info_put(code, doc["$id"], doc.get("referred_by"))
    return (doc["$id"], doc.get("referred_by") or "")


def ensure_refer_code(user):
    if user.get("user_refer_code"):
        return user["user_refer_code"]
    while True:
        code = generate_refer_code()
        if not find_one(C_USERS, "user_refer_code", code):
            break
    update_doc(C_USERS, user["$id"], {"user_refer_code": code, "user_refer_link": f"{INVITE_BASE}{code}"})
    code_info_put(code, user["$id"], user.get("referred_by"))
    return code


# ----------------------------------------------------------------------------
# [નવું] રેફર યાદી સર્વરની યાદમાં
#   દરેક રેફર કરનાર (કોડ) માટે ત્રણેય લેવલના મિત્રોની યાદી મેમરીમાં રહે છે.
#   ડેટાબેઝમાંથી ફક્ત પહેલી વાર (અથવા સર્વર ફરી ચાલુ થયા પછી / ૧૨ કલાક પછી) વંચાય છે.
#   પછી:  નવો સભ્ય જોડાય -> યાદીમાં સીધો ઉમેરાય.   બોનસ મળે -> "બોનસ મળ્યું" સીધું બદલાય.
# ----------------------------------------------------------------------------
_rg = {}                                  # રેફર કોડ -> {"time": સમય, "friends": {મિત્ર id: નોંધ}}
_rg_lock = threading.Lock()
_rg_loading = {}                          # લોડ ચાલુ હોય ત્યારે વચ્ચે આવેલા ફેરફારો અહીં જમા થાય
_rg_load_locks = defaultdict(threading.Lock)
_fast_downline_ok = True
_slow_downline_cache = {}                 # રેફર કોડ -> (સમય, (l1, l2, l3))  [ફક્ત જૂની ધીમી રીત માટે]


def _downline_filter(code, level):
    if level == 1:
        return [q("equal", "referred_by", [code])]
    if level == 2:
        return [q("equal", "referred_by_level2", [code])]
    return [q("equal", "referred_by_level3", [code])]


def downline_all_slow(code):
    """જૂની રીત (બધા મિત્રો વાંચે). ફક્ત ત્યારે વપરાય જો ઝડપી રીત (index) ન ચાલે."""
    hit = _slow_downline_cache.get(code)
    if hit and time.time() - hit[0] < REFER_MEM_SECONDS:
        return hit[1]

    def by_codes(codes):
        docs = []
        for i in range(0, len(codes), 100):
            docs += list_docs(C_USERS, [q("equal", "referred_by", codes[i:i + 100])])
        return docs

    def codes_of(docs):
        return [d["user_refer_code"] for d in docs if d.get("user_refer_code")]

    a = by_codes([code])
    b = by_codes(codes_of(a)) if a else []
    c = by_codes(codes_of(b)) if b else []
    if len(_slow_downline_cache) > 500:
        _slow_downline_cache.clear()
    _slow_downline_cache[code] = (time.time(), (a, b, c))
    return a, b, c


def _friend_rec(level, d):
    return {
        "id": d.get("$id"),
        "name": d.get("user_nickname") or "Friend",
        "paid": d.get("refer_bonus_paid") is True,
        "level": level,
        "createdAt": d.get("$createdAt") or "",
    }


def _load_downline(code):
    """ડેટાબેઝમાંથી એક રેફર કરનારના ત્રણેય લેવલના મિત્રો વાંચે (ફક્ત પહેલી વાર)."""
    global _fast_downline_ok
    friends = {}
    if _fast_downline_ok:
        try:
            for lv in (1, 2, 3):
                for d in list_docs(C_USERS, _downline_filter(code, lv)):
                    friends[d["$id"]] = _friend_rec(lv, d)
            return friends
        except AppwriteError as e:
            if e.status != 400:
                raise
            _fast_downline_ok = False
            friends = {}
            log.warning("ઝડપી રેફર શોધ ચાલી નહીં, જૂની રીત વાપરું છું. એપરાઈટમાં user_information ટેબલ પર "
                        "referred_by_level2 અને referred_by_level3 ના index બનાવો: %s", e)
    l1, l2, l3 = downline_all_slow(code)
    for lv, docs in ((1, l1), (2, l2), (3, l3)):
        for d in docs:
            friends[d["$id"]] = _friend_rec(lv, d)
    return friends


def _rg_apply(friends, op):
    if op[0] == "add":
        rec = op[1]
        friends[rec["id"]] = dict(rec)
    elif op[0] == "paid":
        r = friends.get(op[1])
        if r is not None:
            r["paid"] = True


def rg_get(code):
    """રેફર કરનારની મિત્ર-યાદી (યાદમાંથી). યાદમાં ન હોય તો જ ડેટાબેઝમાંથી વાંચે."""
    now = time.time()
    with _rg_lock:
        e = _rg.get(code)
        if e and now - e["time"] < REFER_MEM_SECONDS:
            return e
    with _rg_load_locks[code]:
        with _rg_lock:
            e = _rg.get(code)
            if e and time.time() - e["time"] < REFER_MEM_SECONDS:
                return e
            pending = []
            _rg_loading[code] = pending
        try:
            friends = _load_downline(code)
        except Exception:
            with _rg_lock:
                _rg_loading.pop(code, None)
            raise
        with _rg_lock:
            _rg_loading.pop(code, None)
            for op in pending:                 # લોડ દરમિયાન આવેલા ફેરફાર પણ લાગુ કરો
                _rg_apply(friends, op)
            if len(_rg) >= REFER_MEM_MAX_USERS:
                oldest = min(_rg, key=lambda k: _rg[k]["time"])
                _rg.pop(oldest, None)
            entry = {"time": time.time(), "friends": friends}
            _rg[code] = entry
        return entry


def rg_add_friend(code, level, rec):
    """નવો સભ્ય જોડાય ત્યારે (સાઇનઅપ). યાદીમાં સીધો ઉમેરો, ડેટાબેઝ વાંચવો નહીં."""
    if not code:
        return
    r = dict(rec)
    r["level"] = level
    with _rg_lock:
        e = _rg.get(code)
        if e is not None:
            e["friends"][r["id"]] = r
        if code in _rg_loading:
            _rg_loading[code].append(("add", r))


def rg_mark_paid(code, friend_id):
    """મિત્રનું બોનસ અપાઈ ગયું: યાદીમાં "બોનસ મળ્યું" કરો."""
    if not code:
        return
    with _rg_lock:
        e = _rg.get(code)
        if e is not None:
            r = e["friends"].get(friend_id)
            if r is not None:
                r["paid"] = True
        if code in _rg_loading:
            _rg_loading[code].append(("paid", friend_id))


def rg_drop(code):
    """એડમિન રિફ્રેશ વખતે (કન્સોલમાં સીધા ફેરફાર પછી) આ યાદી ભૂંસો, આગળ તાજી વંચાશે."""
    if not code:
        return
    with _rg_lock:
        _rg.pop(code, None)
    _slow_downline_cache.pop(code, None)


def rg_view(entry, level, limit, offset):
    """યાદીમાંથી જ પાનું, ગણતરીઓ અને સફળ રેફર. ડેટાબેઝ સાથે કોઈ લેવાદેવા નથી."""
    with _rg_lock:
        vals = list(entry["friends"].values())
    counts = {"1": 0, "2": 0, "3": 0}
    paid = 0
    for v in vals:
        counts[str(v["level"])] = counts.get(str(v["level"]), 0) + 1
        if v.get("paid"):
            paid += 1
    sel = vals if level == 0 else [v for v in vals if v["level"] == level]
    sel.sort(key=lambda v: v.get("createdAt") or "", reverse=True)
    page = sel[offset:offset + limit]
    has_more = offset + len(page) < len(sel)
    return page, has_more, counts, paid


# ----------------------------------------------------------------------------
# [નવું] મિત્રના "મંજૂર થયેલા અલગ ઓફર" ની યાદ
#   ફક્ત એવા મિત્રો માટે જેમને કોઈએ રેફર કર્યા છે અને બોનસ બાકી છે.
#   ટાસ્ક મંજૂર થાય ત્યારે નામ સીધું ઉમેરાય છે, એટલે બોનસ તપાસવા ટાસ્ક ફરી વાંચવા પડતા નથી.
# ----------------------------------------------------------------------------
_done_offers = {}        # મિત્ર id -> {મંજૂર થયેલા ઓફરના નામ}
_done_lock = threading.Lock()


def count_completed_offers(email):
    names = set()
    for d in user_tasks(email):
        if classify_task_status(d.get("task_status")) == "completed" and counts_for_refer(d.get("offer_taskname"), d.get("task_prize")):
            names.add(norm(d.get("offer_taskname")))
    return len(names)


def _completed_names_from_db(email):
    names = set()
    for d in user_tasks(email):
        if classify_task_status(d.get("task_status")) == "completed" and counts_for_refer(d.get("offer_taskname"), d.get("task_prize")):
            names.add(norm(d.get("offer_taskname")))
    return names


def friend_done_set(uid, email):
    """યાદમાં હોય તો તે, નહીંતર ફક્ત એક વાર ડેટાબેઝમાંથી વાંચીને યાદમાં મૂકે."""
    with _done_lock:
        s = _done_offers.get(uid)
    if s is not None:
        return s
    names = _completed_names_from_db(email)
    with _done_lock:
        if len(_done_offers) > 5000:
            _done_offers.clear()
        return _done_offers.setdefault(uid, names)


def note_task_done(uid, email, offer_name):
    """નવો મંજૂર થયેલો ઓફર યાદીમાં ઉમેરે અને કુલ અલગ ઓફરની સંખ્યા આપે."""
    s = friend_done_set(uid, email)   # ડેટાબેઝમાંથી વંચાય તો તેમાં આ ટાસ્ક (હમણાં success થયેલો) આવી જ ગયો હોય
    with _done_lock:
        s.add(norm(offer_name))
        return len(s)


# ----------------------------------------------------------------------------
# ખાતું બનાવવું અને લોગિન
# ----------------------------------------------------------------------------
@app.post("/api/signup")
def signup():
    d = request.get_json(silent=True) or {}
    nickname = clean_nickname(d.get("nickname", ""))
    email = str(d.get("email", "")).strip()
    password = str(d.get("password", ""))
    refer_code = str(d.get("referCode", "")).strip()

    if not nickname:
        return err("Nickname is required")
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return err("Invalid email")
    if len(password) < 7:
        return err("Password must be at least 7 characters long")

    with _signup_lock:
        if find_one(C_USERS, "user_gmail_account", email):
            return err("Email already registered!")

        referrer = None
        if refer_code:
            referrer = find_one(C_USERS, "user_refer_code", refer_code)
            if not referrer:
                return err("Invalid refer code")
            if referrer.get("user_gmail_account") == email:
                return err("You cannot use your own refer code")
            code_info_put(referrer.get("user_refer_code"), referrer["$id"], referrer.get("referred_by"))

        level2 = (referrer.get("referred_by") or "") if referrer else ""
        level3 = (referrer.get("referred_by_level2") or "") if referrer else ""

        # રેફર કોડ ખાતું બનાવતી વખતે જ બને છે, એટલે એપ ખુલે ત્યારે અલગથી બનાવવા-લખવાનું નહીં
        while True:
            new_code = generate_refer_code()
            if not find_one(C_USERS, "user_refer_code", new_code):
                break

        new_doc = create_doc(C_USERS, {
            "user_nickname": nickname,
            "user_gmail_account": email,
            "user_password": password,
            "referred_by": refer_code,
            "referred_by_level2": level2,
            "referred_by_level3": level3,
            "refer_bonus_paid": False,
            "user_refer_code": new_code,
            "user_refer_link": f"{INVITE_BASE}{new_code}",
        })
        code_info_put(new_code, new_doc.get("$id"), refer_code)

    # [નવું] ઉપરના ૩ લેવલની મિત્ર-યાદીમાં નવો સભ્ય સીધો ઉમેરો (ડેટાબેઝ ફરી વાંચવો નહીં)
    friend_rec = {
        "id": new_doc.get("$id"),
        "name": nickname,
        "paid": False,
        "createdAt": new_doc.get("$createdAt") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    if referrer:
        rg_add_friend(referrer.get("user_refer_code") or refer_code, 1, friend_rec)
    if level2:
        rg_add_friend(level2, 2, friend_rec)
    if level3:
        rg_add_friend(level3, 3, friend_rec)

    # ઉપરના ૩ લેવલને નવા સભ્યની જાણ
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    targets = []
    if referrer:
        targets.append(referrer["$id"])
    for code in (level2, level3):
        if code:
            try:
                info = code_info(code)   # [નવું] યાદમાંથી, ન હોય તો જ ડેટાબેઝ
                if info:
                    targets.append(info[0])
            except AppwriteError:
                pass
    for doc_id in targets:
        try:
            update_doc(C_USERS, doc_id, {"refer_new_join_time": now_iso})
        except AppwriteError:
            pass

    return jsonify({"ok": True})


@app.post("/api/login")
def login():
    d = request.get_json(silent=True) or {}
    email = str(d.get("email", "")).strip()
    password = str(d.get("password", ""))
    key = f"{request.remote_addr}|{email.lower()}"
    if too_many_failures(key):
        return err("Too many attempts. Try again after 10 minutes", 429)

    user = find_one(C_USERS, "user_gmail_account", email)
    if not user:
        return err("This account is not registered", 404)
    if not verify_password(user, password):
        _failed[key].append(time.time())
        return err("Wrong Password", 401)

    _failed.pop(key, None)
    return jsonify({
        "token": make_token(user),
        "email": user["user_gmail_account"],
        "nickname": user.get("user_nickname") or "",
        "id": user["$id"],
    })


# ----------------------------------------------------------------------------
# વપરાશકર્તાની માહિતી
# ----------------------------------------------------------------------------
@app.get("/api/me")
@auth_required
def me():
    u = g.user
    code = ensure_refer_code(u)
    return jsonify({
        "id": u["$id"],
        "email": u.get("user_gmail_account"),
        "nickname": u.get("user_nickname") or "",
        "balance": float(u.get("total_balance_available") or 0),
        "referNumber": u.get("user_refer_number") or 0,
        "referEarning": u.get("user_refer_earning") or 0,
        "upi": u.get("user_addupi_id") or "",
        "referCode": code,
        "referLink": f"{INVITE_BASE}{code}",
    })


# ----------------------------------------------------------------------------
# તરત સંદેશનું ખુલ્લું જોડાણ. એપ ખુલ્લી હોય ત્યારે જ HTML આ જોડે છે.
# ----------------------------------------------------------------------------
@app.get("/api/stream")
@auth_required
def stream():
    uid = g.user["$id"]
    with _stream_lock:
        total = sum(len(v) for v in _streams.values())
        if total >= MAX_STREAMS_TOTAL and not _streams.get(uid):
            return err("Server busy", 503)
        mine = _streams.setdefault(uid, [])
        while len(mine) >= MAX_STREAMS_PER_USER:
            old = mine.pop(0)
            try:
                old.put_nowait(None)  # સૌથી જૂનું જોડાણ બંધ કરો
            except queue.Full:
                pass
        qu = queue.Queue(maxsize=50)
        mine.append(qu)

    def gen():
        started = time.time()
        try:
            yield "retry: 5000\n\n"
            while time.time() - started < STREAM_MAX_SECONDS:
                try:
                    item = qu.get(timeout=STREAM_PING_SECONDS)
                except queue.Empty:
                    yield ": ping\n\n"
                    continue
                if item is None:
                    break
                yield "data: " + json.dumps(item, ensure_ascii=False) + "\n\n"
        finally:
            with _stream_lock:
                lst = _streams.get(uid)
                if lst is not None:
                    if qu in lst:
                        lst.remove(qu)
                    if not lst:
                        _streams.pop(uid, None)

    resp = Response(gen(), mimetype="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp


# ----------------------------------------------------------------------------
# એડમિન પેનલ માટે: "આ યુઝરનો ડેટા તાજો કરો"
# ----------------------------------------------------------------------------
@app.post("/api/admin/refresh")
def admin_refresh():
    given = request.headers.get("X-Admin-Secret", "")
    if not ADMIN_SECRET or not hmac.compare_digest(given.encode("utf-8"), ADMIN_SECRET.encode("utf-8")):
        return err("Forbidden", 403)

    email = str((request.get_json(silent=True) or {}).get("email", "")).strip()
    if not email:
        return err("Email missing")
    user = find_one(C_USERS, "user_gmail_account", email)
    if not user:
        return err("User not found", 404)

    uid = user["$id"]
    drop_user_caches(uid)           # યુઝરની રો ભૂંસો
    forget_user_cache(email)        # ટાસ્ક અને ઇતિહાસની યાદી ભૂંસો
    rg_drop(user.get("user_refer_code"))   # [નવું] આ યુઝરની રેફર મિત્ર-યાદી ભૂંસો, આગળ તાજી વંચાશે
    with _done_lock:
        _done_offers.pop(uid, None)        # [નવું] મંજૂર ટાસ્કના નામની યાદ ભૂંસો
    udoc, tdocs = None, None
    try:
        udoc = get_user_for_auth(uid)                                # તાજું બેલેન્સ વગેરે
        tdocs = cached_user_list("tasks", email, user_tasks)          # તાજા ટાસ્ક
    except AppwriteError as e:
        log.warning("એડમિન રિફ્રેશમાં તાજો ડેટા ન વંચાયો: %s", e)

    # મિત્રના ટાસ્ક પૂરા થયા હોય તો રેફર ઇનામ આ જ ક્ષણે આપો
    if udoc is not None and tdocs is not None:
        try_pay_own_referral(udoc, tdocs, seed=True)

    # યુઝરની એપ ખુલ્લી હોય તો નવો ડેટા તરત મોકલો
    try:
        if user_is_connected(uid) and udoc is not None:
            payload = dict(user_push_basics(udoc))
            if tdocs is not None:
                payload["tasks"] = [pick(d, TASK_FIELDS) for d in tdocs]
            page = cached_user_list("history_p1", email, lambda e: user_history_page(e, HISTORY_PUSH_LIMIT, 0))
            if page.get("limit") != HISTORY_PUSH_LIMIT:
                page = user_history_page(email, HISTORY_PUSH_LIMIT, 0)
            payload["entries"] = [pick(d, HISTORY_FIELDS) for d in page["docs"]]
            payload["reloadRefer"] = True
            push_user(uid, payload)
    except Exception as e:  # noqa
        log.warning("એડમિન રિફ્રેશ પછી એપને તરત મોકલી ન શકાયું: %s", e)
    return jsonify({"ok": True})


def admin_authorized():
    given = request.headers.get("X-Admin-Secret", "")
    return bool(ADMIN_SECRET) and hmac.compare_digest(given.encode("utf-8"), ADMIN_SECRET.encode("utf-8"))


# ----------------------------------------------------------------------------
# એડમિન ટાસ્ક મંજૂર કરે ત્યારે ફક્ત આ રસ્તો બોલાવે (X-Admin-Secret સાથે).
#   ૧) ઇનામની નોંધ બનાવે  ૨) બેલેન્સ વધારે  ૩) ટાસ્ક "મંજૂર" કરે
#   ૪) [નવું] મિત્રના મંજૂર ટાસ્કની યાદમાં નામ ઉમેરે, ૩ અલગ ઓફર થાય તો રેફર ઇનામ આપે (ડેટાબેઝ વાંચ્યા વગર)
#   ૫) સર્વરની યાદ બદલે અને ખુલ્લી એપને તરત નવી રકમ મોકલે
# માંગ: {"taskId": "<user_task_approval નો $id>", "reason": "..."}  અથવા  {"email": "...", "taskName": "..."}
# ----------------------------------------------------------------------------
@app.post("/api/admin/task-approved")
def admin_task_approved():
    if not admin_authorized():
        return err("Forbidden", 403)

    d = request.get_json(silent=True) or {}
    task_id = str(d.get("taskId") or "").strip()
    email_in = str(d.get("email") or "").strip()
    task_name = str(d.get("taskName") or "").strip()
    reason = str(d.get("reason") or "").strip()  # એડમિને લખેલું કારણ, યુઝરને દેખાય છે

    if task_id:
        try:
            task = get_doc(C_TASKS, task_id)
        except AppwriteError as e:
            if e.status == 404:
                return err("Task not found", 404)
            raise
    elif email_in and task_name:
        task = latest_by_offer(user_tasks(email_in)).get(norm(task_name))
        if not task:
            return err("Task not found", 404)
    else:
        return err("taskId or email + taskName missing")

    task_id = task["$id"]
    email = task.get("user_gmail_account") or ""
    if not email or (email_in and norm(email_in) != norm(email)):
        return err("Email does not match this task")

    uid = str(d.get("userId") or "").strip()
    if not uid:
        user0 = find_one(C_USERS, "user_gmail_account", email)
        if not user0:
            return err("User not found", 404)
        uid = user0["$id"]

    already_done = classify_task_status(task.get("task_status")) == "completed"
    prize = float(task.get("task_prize") or 0)
    if prize <= 0:
        for o in cached_offers():
            if norm(o.get("taskName")) == norm(task.get("offer_taskname")):
                prize = float(o.get("offer_prize") or 0)
                break
    if prize <= 0 and not already_done:
        return err("Reward amount not found")

    entry_id = "t_" + task_id
    now = ist_now()
    time_str, stamp = time_date_str(now), int(time.time() * 1000)
    new_hist = None
    task_doc = task
    task_name_txt = task.get("offer_taskname") or "Task"

    with user_lock(uid):
        fresh = get_doc(C_USERS, uid)
        if norm(fresh.get("user_gmail_account")) != norm(email):
            return err("Email does not match this task")
        user_doc = fresh
        if not already_done:
            try:
                get_doc(C_HISTORY, entry_id)
                credited = True  # આ ઇનામ પહેલેથી અપાઈ ગયું છે
            except AppwriteError as e:
                if e.status != 404:
                    raise
                credited = False
            if not credited:
                balance = float(fresh.get("total_balance_available") or 0)
                new_hist = create_doc(C_HISTORY, {
                    "user_gmail_account": email,
                    "entry_id": entry_id, "type": "reward",
                    "title": f"{task_name_txt} Task Reward",
                    "amount": float(prize), "status": "success",
                    "date": time_str, "timestamp": stamp,
                }, doc_id=entry_id)
                try:
                    user_doc = update_doc(C_USERS, uid, {"total_balance_available": round(balance + prize, 2)})
                except Exception:
                    try:
                        _call("DELETE", f"/collections/{C_HISTORY}/documents/{entry_id}")
                    except Exception as e2:  # noqa
                        log.error("ઇનામની નોંધ પાછી કાઢી શકાઈ નહીં %s: %s", entry_id, e2)
                    raise
            task_fields = {"task_status": "success"}
            if reason:
                task_fields["task_approval_reason"] = reason
            task_doc = update_doc(C_TASKS, task_id, task_fields)

    # સર્વરની યાદ તરત બદલો (ફરી વાંચવું નહીં)
    if not already_done:
        cache_replace_task(email, task_doc)
        if new_hist is not None:
            cache_add_history(email, new_hist)
        refresh_task_stats_from_cache(user_doc)

        # [નવું] મિત્રના અલગ ૩ ઓફર પૂરા થયા હોય તો ઉપરના ૩ લેવલને રેફર ઇનામ આ જ ક્ષણે
        try:
            referral_progress(uid, fresh, task.get("offer_taskname"), prize)
        except Exception as e:  # noqa
            log.warning("ટાસ્ક મંજૂર પછી રેફર ઇનામ તપાસમાં ભૂલ (%s): %s", email, e)

        # ખુલ્લી એપને તરત મોકલો
        payload = dict(user_push_basics(user_doc))
        payload["tasks"] = [pick(task_doc, TASK_FIELDS)]
        if new_hist is not None:
            payload["entries"] = [pick(new_hist, HISTORY_FIELDS)]
        push_user(uid, payload)

    return jsonify({"ok": True, "already": already_done, "balance": user_push_basics(user_doc)["balance"]})


# ----------------------------------------------------------------------------
# એડમિન ઉપાડ મંજૂર/નકાર કરે ત્યારે આ રસ્તો બોલાવે (X-Admin-Secret સાથે).
# માંગ: {"requestId": "<withdraw_request નો $id>", "status": "success" અથવા "reject", "email": "...",
#        "writeDb": false}
# ----------------------------------------------------------------------------
@app.post("/api/admin/withdraw-status")
def admin_withdraw_status():
    if not admin_authorized():
        return err("Forbidden", 403)
    d = request.get_json(silent=True) or {}
    req_id = str(d.get("requestId") or "").strip()
    st = norm(d.get("status"))
    if st == "rejected":
        st = "reject"
    if not req_id or st not in ("success", "reject"):
        return err("requestId and status (success or reject) are required")

    entry_id = "w_" + req_id
    email = str(d.get("email") or "").strip()
    hist = None

    if d.get("writeDb") is False:
        if not email:
            return err("email is required when writeDb is false")
    else:
        try:
            w = update_doc(C_WITHDRAW, req_id, {"payout_status1": st})
        except AppwriteError as e:
            if e.status == 404:
                return err("Withdraw request not found", 404)
            raise
        email = str(w.get("user_gmail_account1") or email).strip()
        try:
            hist = update_doc(C_HISTORY, entry_id, {"status": st})
        except AppwriteError as e:
            if e.status != 404:
                log.warning("ઇતિહાસની સ્થિતિ બદલી ન શકાઈ %s: %s", entry_id, e)

    if email:
        cache_set_history_status(email, entry_id, st)
        uid = str(d.get("userId") or "").strip()
        if not uid:
            u = find_one(C_USERS, "user_gmail_account", email)
            uid = u["$id"] if u else ""
        if uid:
            payload = {"withdrawUpdated": True}
            if hist is not None:
                payload["entries"] = [pick(hist, HISTORY_FIELDS)]
            push_user(uid, payload)
    return jsonify({"ok": True, "status": st})


@app.get("/api/config")
def config():
    """બધા નિયમો અને રકમ (લૉગિન વગર પણ). HTML ફક્ત આ બતાવે છે, પોતે કંઈ નક્કી કરતું નથી."""
    return jsonify({
        "minWithdraw": MIN_WITHDRAW,
        "maxWithdraw": MAX_WITHDRAW,
        "feePercent": FEE_PERCENT,
        "feeFreeBelow": FEE_FREE_BELOW,
        "quickAmounts": QUICK_AMOUNTS,
        "referRewards": {str(k): v for k, v in REFER_REWARDS.items()},
        "referTasksNeeded": REFER_TASKS_NEEDED,
    })


@app.post("/api/upi")
@auth_required
def set_upi():
    upi = str((request.get_json(silent=True) or {}).get("upi", "")).strip()
    if not re.match(r"^\S{3,100}$", upi) or "@" not in upi:
        return err("Enter a valid UPI ID")
    update_doc(C_USERS, g.user["$id"], {"user_addupi_id": upi})
    return jsonify({"ok": True})


# ----------------------------------------------------------------------------
# ઓફર, ટાસ્ક, ઇતિહાસ
# ----------------------------------------------------------------------------
OFFER_FIELDS = ["$id", "taskName", "offer_subtitle", "offer_subtitles", "offer_prize", "offer_logo",
                "offer_filter_time", "offer_filter_count_step", "offer_link", "offer_step",
                "offer_stepincode", "offer_example_photo", "offer_notice"]
TASK_FIELDS = ["$id", "$createdAt", "offer_taskname", "task_status", "task_approval_reason", "warning_count",
               "warning_time", "is_permanent_warning", "reject_count", "reject_time", "is_permanent_reject"]
HISTORY_FIELDS = ["$id", "$createdAt", "entry_id", "type", "title", "amount", "status", "date", "timestamp"]


@app.get("/api/offers")
def offers():
    return jsonify({"documents": [pick(d, OFFER_FIELDS) for d in cached_offers()]})


@app.get("/api/tasks")
@auth_required
def tasks():
    docs = cached_user_list("tasks", g.user["user_gmail_account"], user_tasks)
    try_pay_own_referral(g.user, docs)
    return jsonify({"documents": [pick(d, TASK_FIELDS) for d in docs]})


@app.get("/api/history")
@auth_required
def history():
    # ?fresh=1 આવે (એડમિને સ્થિતિ બદલી ત્યારે એપ આ મોકલે) તો આ યુઝરની યાદ ભૂંસીને તાજો ઇતિહાસ આપો.
    # એક યુઝર માટે ૩ સેકન્ડમાં એક જ વાર ભૂંસાય, જેથી વારંવાર માંગીને સર્વર પર ભાર ન પડે.
    if request.args.get("fresh") == "1":
        _uid_f, _now_f = g.user["$id"], time.time()
        if _now_f - _last_fresh_history.get(_uid_f, 0) >= 3:
            _last_fresh_history[_uid_f] = _now_f
            forget_user_cache(g.user["user_gmail_account"], "history")
    # પાનાં પ્રમાણે: /api/history?limit=30&offset=0. limit ન આપો તો જૂની રીત (બધી નોંધ) જ ચાલે.
    if request.args.get("limit") is not None:
        email = g.user["user_gmail_account"]
        limit = max(1, min(100, safe_int(request.args.get("limit")) or 30))
        offset = max(0, safe_int(request.args.get("offset")))
        try:
            if offset == 0:
                page = cached_user_list("history_p1", email, lambda e: user_history_page(e, limit, 0))
                if page.get("limit") != limit:
                    page = user_history_page(email, limit, 0)
            else:
                page = user_history_page(email, limit, offset)
            return jsonify({"documents": [pick(d, HISTORY_FIELDS) for d in page["docs"]],
                            "hasMore": page["hasMore"]})
        except AppwriteError as e:
            log.warning("પાનાં પ્રમાણે ઇતિહાસ ચાલ્યો નહીં, જૂની રીત વાપરું છું: %s", e)
    docs = cached_user_list("history", g.user["user_gmail_account"], user_history)
    return jsonify({"documents": [pick(d, HISTORY_FIELDS) for d in docs]})


@app.post("/api/sync-stats")
@auth_required
def sync_stats():
    uid, now = g.user["$id"], time.time()
    if now - _last_stats_sync.get(uid, 0) >= STATS_SYNC_MIN_SECONDS:
        _last_stats_sync[uid] = now
        refresh_task_stats_from_cache(g.user)  # યાદ રાખેલી યાદી પરથી જ, નવું વાંચન નહીં
    return jsonify({"ok": True})


# ----------------------------------------------------------------------------
# ટાસ્કના ફોટા મોકલવા (ImgBB ની કી અહીં જ રહે છે)
# ----------------------------------------------------------------------------
def upload_photo(data, filename, mimetype):
    try:
        r = requests.post(
            "https://api.imgbb.com/1/upload",
            params={"key": IMGBB_KEY},
            files={"image": (filename or "photo.jpg", data, mimetype)},
            timeout=60,
        )
        body = r.json()
        if body.get("success"):
            return body["data"]["url"]
    except Exception as e:  # noqa
        log.warning("ફોટો અપલોડ નિષ્ફળ: %s", e.__class__.__name__)
    return None


@app.post("/api/upload-photo")
@auth_required
def upload_photo_route():
    if not IMGBB_KEY:
        return err("Photo upload is not configured on the server", 500)
    f = request.files.get("image")
    if not f:
        return err("Photo missing")
    data = f.read()
    if not (f.mimetype or "").startswith("image/") or not data:
        return err("Only image files are allowed")
    if len(data) > MAX_PHOTO_BYTES:
        return err("Each photo must be under 8 MB")
    url = upload_photo(data, f.filename, f.mimetype)
    if not url:
        return err("Photo upload failed. Try again", 502)
    return jsonify({"url": url})


@app.post("/api/submit-task")
@auth_required
def submit_task():
    if not IMGBB_KEY:
        return err("Photo upload is not configured on the server", 500)

    offer_id = request.form.get("offer_id", "").strip()
    if not offer_id:
        return err("Offer missing")
    try:
        offer = get_doc(C_OFFERS, offer_id)
    except AppwriteError as e:
        if e.status == 404:
            return err("Offer not found", 404)
        raise

    files = request.files.getlist("photos")
    if not 1 <= len(files) <= MAX_PHOTOS:
        return err(f"Upload 1 to {MAX_PHOTOS} photos")
    photos = []
    for f in files:
        data = f.read()
        if not (f.mimetype or "").startswith("image/") or not data:
            return err("Only image files are allowed")
        if len(data) > MAX_PHOTO_BYTES:
            return err("Each photo must be under 8 MB")
        photos.append((data, f.filename, f.mimetype))

    user = g.user
    email = user["user_gmail_account"]

    with user_lock(user["$id"]):
        tasks_docs = user_tasks(email)
        existing = latest_by_offer(tasks_docs).get(norm(offer.get("taskName")))
        status = effective_status(existing)
        if status in ("review", "completed"):
            return err("This offer is already submitted", 409)
        if status in ("rejected", "warning"):
            return err("This offer is locked right now", 409)

        urls = [u for u in (upload_photo(*p) for p in photos) if u]
        if not urls:
            return err("Photo upload failed. Try again", 502)

        stats = compute_stats(cached_offers(), tasks_docs, [])  # ઇતિહાસ વાંચવો નહીં, ટાસ્કના આંકડા ટાસ્ક પરથી જ
        now = ist_now()
        timeline = f"{now.day} {now.strftime('%b')} {now.strftime('%H:%M:%S')}"

        new_task = create_doc(C_TASKS, {
            "user_nickname": user.get("user_nickname") or "Unknown User",
            "user_gmail_account": email,
            "user_complete_task": stats["user_complete_task"],
            "user_reject_task": stats["user_rejected_task"],
            "user_pending_task": stats["user_pending_task"] + 1,
            "user_total_task": stats["user_total_task"] + 1,
            # ઇનામની રકમ ઓફરના ડેટામાંથી જ લેવાય છે, વપરાશકર્તા મોકલે તે નહીં
            "task_prize": float(offer.get("offer_prize") or 0),
            "task_status": "pending",
            "offer_logo": offer.get("offer_logo") or "",
            "offer_taskname": offer.get("taskName") or "",
            "task_submit_photo": urls,
            "task_approval_reason": "",
            "task_timeline": timeline,
        })
        # યાદ ભૂંસવાને બદલે નવો ટાસ્ક સીધો યાદમાં ઉમેરો (ફરી વાંચવું નહીં)
        if not cache_replace_task(email, new_task):
            forget_user_cache(email, "tasks")

    # બધું ફરી વાંચીને ગણવાને બદલે, હમણાં જ ગણેલા આંકડા (+1 સાથે) યુઝર રોમાં લખી દો
    save_user_stats(user, {
        "user_complete_task": stats["user_complete_task"],
        "user_rejected_task": stats["user_rejected_task"],
        "user_pending_task": stats["user_pending_task"] + 1,
        "user_total_task": stats["user_total_task"] + 1,
    })
    return jsonify({"ok": True})


# ----------------------------------------------------------------------------
# પૈસા ઉપાડવાની વિનંતી (મુખ્ય હિસાબ અહીં)
# ----------------------------------------------------------------------------
def calc_fee(amt):
    """ફી = ૨%, પણ ₹૩૦ થી ઓછી રકમ પર ૦. પૈસા (બે અંક) સુધી ગણાય."""
    a = Decimal(str(amt))
    if a < FEE_FREE_BELOW:
        fee = Decimal("0.00")
    else:
        fee = (a * Decimal(FEE_PERCENT) / Decimal(100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(fee), float(a - fee)


def withdraw_problem(amt, balance):
    if amt < MIN_WITHDRAW:
        return f"Minimum withdraw is {MIN_WITHDRAW}₹"
    if amt > balance + 1e-9:
        return "Insufficient balance"
    if amt > MAX_WITHDRAW:
        return f"Maximum withdraw is {MAX_WITHDRAW}₹"
    return None


def parse_amount(raw):
    try:
        amt = round(float(raw), 2)
    except (TypeError, ValueError):
        return None
    return amt if math.isfinite(amt) else None


@app.get("/api/withdraw-quote")
@auth_required
def withdraw_quote():
    amt = parse_amount(request.args.get("amount"))
    balance = float(g.user.get("total_balance_available") or 0)
    if amt is None:
        amt = 0.0
    problem = withdraw_problem(amt, balance)
    fee, net = calc_fee(amt) if amt > 0 else (0.0, 0.0)
    return jsonify({"ok": problem is None, "error": problem or "", "amount": amt, "fee": fee, "net": net})


@app.post("/api/withdraw")
@auth_required
def withdraw():
    d = request.get_json(silent=True) or {}
    amt = parse_amount(d.get("amount"))
    if amt is None:
        return err("Invalid amount")

    uid = g.user["$id"]
    with user_lock(uid):  # એક સાથે બે વિનંતી આવે તો પણ બેલેન્સ બે વાર ન ઘટે
        user = get_doc(C_USERS, uid)
        email = user["user_gmail_account"]
        balance = float(user.get("total_balance_available") or 0)
        upi = str(user.get("user_addupi_id") or "").strip()

        if not upi or upi == "Not set":
            return err("Please add your UPI ID first")
        problem = withdraw_problem(amt, balance)
        if problem:
            return err(problem)

        fee, net = calc_fee(amt)  # બેલેન્સમાંથી પૂરી રકમ કપાય, નોંધમાં ફી કાપ્યા પછીની રકમ
        new_balance = round(balance - amt, 2)
        # પહેલા બેલેન્સ ઘટાડો, પછી નોંધ. વચ્ચે ભૂલ થાય તો બેલેન્સ પાછું મૂકી દેવાય.
        update_doc(C_USERS, uid, {"total_balance_available": new_balance})
        try:
            counts = [0, 0, 0, 0]  # કુલ, સફળ, નામંજૂર, બાકી
            for w in list_docs(C_WITHDRAW, [q("equal", "user_gmail_account1", [email])]):
                counts[0] += 1
                st = norm(w.get("payout_status1") or "pending")
                if "success" in st or "complete" in st:
                    counts[1] += 1
                elif "reject" in st or "fail" in st:
                    counts[2] += 1
                else:
                    counts[3] += 1
            counts[0] += 1
            counts[3] += 1

            now = ist_now()
            time_str = time_date_str(now)
            stamp = int(time.time() * 1000)

            req_doc = create_doc(C_WITHDRAW, {
                "user_withdraw_request_time_date1": time_str,
                "user_nickname1": user.get("user_nickname") or "Unknown",
                "user_gmail_account1": email,
                "user_password1": "",  # પાસવર્ડ હવે ક્યાંય નકલ થતો નથી
                "user_total_withdraw1": counts[0],
                "user_total_successwithdraw1": counts[1],
                "user_total_rejectwithdraw1": counts[2],
                "user_total_pendingwithdraw1": counts[3],
                "user_addupi_id1": upi,
                "user_withdraw_amount1": net,
                "withdraw_payout_no1": str(counts[0]),
                "payout_status1": "pending",
            })
        except Exception:
            try:
                update_doc(C_USERS, uid, {"total_balance_available": balance})
            except Exception as e2:  # noqa
                log.error("બેલેન્સ પાછું મૂકી શકાયું નહીં uid=%s balance=%s: %s", uid, balance, e2)
            raise

        entry_id = "w_" + req_doc["$id"]
        entry = {
            "entry_id": entry_id, "type": "withdraw", "title": "Withdraw amount",
            "amount": -net, "status": "pending", "date": time_str, "timestamp": stamp,
        }
        try:
            hist = create_doc(C_HISTORY, {"user_gmail_account": email, **entry}, doc_id=entry_id)
            entry = pick(hist, HISTORY_FIELDS)
            cache_add_history(email, hist)  # યાદ ભૂંસવાને બદલે નવી નોંધ સીધી યાદમાં
        except AppwriteError as e:
            log.error("ઇતિહાસની નોંધ ન થઈ: %s", e)
            forget_user_cache(email, "history")

    # ઉપાડની ગણતરી ઉપર થઈ ગઈ છે (counts), એ જ યુઝર રોમાં લખો. ટાસ્ક અને ઇતિહાસ ફરી વાંચવા નહીં
    save_user_stats(user, {
        "user_total_withdraw": counts[0],
        "user_total_successwithdraw": counts[1],
        "user_total_rejectedwithdraw": counts[2],
        "user_total_pendingwithdraw": counts[3],
    })
    return jsonify({"balance": new_balance, "entry": entry, "fee": fee, "net": net})


# ----------------------------------------------------------------------------
# રેફરલ (લેવલ ૧, ૨, ૩) - [નવું] બધું સર્વરની યાદમાંથી
# /api/referrals?level=0|1|2|3&limit=10&offset=0&counts=1
# ----------------------------------------------------------------------------
@app.get("/api/referrals")
@auth_required
def referrals():
    user = g.user
    code = ensure_refer_code(user)
    uid = user["$id"]

    level = safe_int(request.args.get("level"))
    if level not in (0, 1, 2, 3):
        level = 0
    limit = max(1, min(50, safe_int(request.args.get("limit")) or 10))
    offset = max(0, safe_int(request.args.get("offset")))
    want_counts = request.args.get("counts") == "1"

    entry = rg_get(code)   # યાદમાં હોય તો ડેટાબેઝ સાથે કોઈ વાત નહીં
    page, has_more, counts, paid = rg_view(entry, level, limit, offset)

    # "Success Refer" સંખ્યા યાદીમાંથી જ ગણાઈ. રોમાં અલગ હોય તો જ એક વાર લખો (વાંચન નહીં)
    if safe_int(user.get("user_refer_number")) != paid:
        try:
            update_doc(C_USERS, uid, {"user_refer_number": paid})
        except AppwriteError:
            pass
    refer_earning = user.get("user_refer_earning") or 0

    items = [{
        "id": v.get("id"),
        "name": v.get("name") or "Friend",
        "paid": bool(v.get("paid")),
        "level": v["level"],
        "amount": REFER_REWARDS.get(v["level"], 0),
        "createdAt": v.get("createdAt") or "",
    } for v in page]

    payload = {
        "items": items, "hasMore": has_more, "level": level,
        "referNumber": paid,
        "referEarning": refer_earning,
    }
    if want_counts:
        payload["counts"] = counts
        payload["signature"] = "|".join(str(x) for x in (
            counts["1"], counts["2"], counts["3"], paid, refer_earning))
    return jsonify(payload)


# ----------------------------------------------------------------------------
# રેફરલ ઇનામ સર્વર પોતે આપે છે (એડમિન પેનલનું કોઈ કામ નથી)
# ----------------------------------------------------------------------------
def upline_chain(friend):
    """મિત્રને રેફર કરનાર (લેવલ ૧), તેને રેફર કરનાર (લેવલ ૨), તેને રેફર કરનાર (લેવલ ૩).
    [નવું] કોડ -> યુઝરની યાદમાંથી, ડેટાબેઝ ફક્ત પહેલી વાર."""
    chain, code, seen = [], friend.get("referred_by"), {friend.get("user_refer_code")}
    for level in (1, 2, 3):
        if not code or code in seen:
            break
        seen.add(code)
        info = code_info(code)
        if not info or info[0] == friend["$id"]:
            break
        chain.append((level, {"$id": info[0], "code": code}))
        code = info[1]
    return chain


def pay_referral_bonus(friend_id, friend=None, done_count=None):
    """એક મિત્ર માટે ઉપરના ૩ લેવલને ઇનામ આપે. ફરી ચલાવો તો પણ બે વાર ન જાય.
    friend અને done_count આપ્યા હોય તો ફરી વાંચવું પડતું નથી."""
    with user_lock(friend_id):
        if friend is None:
            friend = get_doc(C_USERS, friend_id)
        if friend.get("refer_bonus_paid") is True or not friend.get("referred_by"):
            return False
        if done_count is None:
            done_count = len(friend_done_set(friend_id, friend["user_gmail_account"]))
        if done_count < REFER_TASKS_NEEDED:
            return False

        now = ist_now()
        time_str, stamp = time_date_str(now), int(time.time() * 1000)
        chain = upline_chain(friend)

        for level, up in chain:
            reward = REFER_REWARDS.get(level, 0)
            if reward <= 0:
                continue
            entry_id = f"rb_{friend_id}_{level}"  # નક્કી નંબર, એટલે એ જ ઇનામની બીજી નોંધ બની ન શકે
            with user_lock(up["$id"]):
                try:
                    get_doc(C_HISTORY, entry_id)
                    continue  # આ ઇનામ પહેલેથી અપાઈ ગયું છે
                except AppwriteError as e:
                    if e.status != 404:
                        raise
                fresh = get_doc(C_USERS, up["$id"])   # પૈસાનો હિસાબ હોવાથી હંમેશા તાજી રો
                balance = float(fresh.get("total_balance_available") or 0)
                earning = float(fresh.get("user_refer_earning") or 0)
                hist_doc = create_doc(C_HISTORY, {
                    "user_gmail_account": fresh["user_gmail_account"],
                    "entry_id": entry_id, "type": "refer_bonus",
                    "title": f"Refer Bonus - Level {level}",
                    "amount": float(reward), "status": "success",
                    "date": time_str, "timestamp": stamp,
                }, doc_id=entry_id)
                try:
                    upd = update_doc(C_USERS, up["$id"], {
                        "total_balance_available": round(balance + reward, 2),
                        "user_refer_earning": int_if_whole(earning + reward),
                        "user_refer_number": int_if_whole(float(fresh.get("user_refer_number") or 0) + 1),
                    })
                except Exception:
                    try:
                        _call("DELETE", f"/collections/{C_HISTORY}/documents/{entry_id}")
                    except Exception as e2:  # noqa
                        log.error("ઇનામની નોંધ પાછી કાઢી શકાઈ નહીં %s: %s", entry_id, e2)
                    raise
                # યાદ ભૂંસવાને બદલે નવી નોંધ સીધી યાદમાં ઉમેરો અને ઉપરના યુઝરની ખુલ્લી એપને તરત મોકલો
                cache_add_history(fresh["user_gmail_account"], hist_doc)
                rg_mark_paid(up["code"], friend_id)   # [નવું] રેફર કરનારની યાદીમાં "બોનસ મળ્યું"
                try:
                    push_user(up["$id"], {
                        **user_push_basics(upd),
                        "entries": [pick(hist_doc, HISTORY_FIELDS)],
                        "reloadRefer": True,
                    })
                except Exception as e3:  # noqa
                    log.warning("રેફર ઇનામ એપને તરત મોકલી ન શકાયું: %s", e3)
                log.info("રેફર ઇનામ ₹%s આપ્યું: લેવલ %s, %s", reward, level, fresh["user_gmail_account"])

        update_doc(C_USERS, friend_id, {"refer_bonus_paid": True})
        for _lv, up in chain:                      # [નવું] બધી યાદીમાં આ મિત્ર "બોનસ મળ્યું"
            rg_mark_paid(up["code"], friend_id)
        with _done_lock:
            _done_offers.pop(friend_id, None)     # હવે આ મિત્ર માટે ગણતરી યાદ રાખવાની જરૂર નથી
    return True


def referral_progress(uid, friend, offer_name, prize=None):
    """મિત્રનો એક ટાસ્ક મંજૂર થયો: યાદમાં નામ ઉમેરો, અલગ ૩ ઓફર થાય તો જ બોનસ આપો."""
    if not counts_for_refer(offer_name, prize):
        return  # [નવું] ટેલિગ્રામ અને ૪૦ થી ઓછા ઇનામ વાળા ટાસ્ક રેફરમાં ગણાતા નથી
    if not friend.get("referred_by") or friend.get("refer_bonus_paid") is True:
        return
    cnt = note_task_done(uid, friend["user_gmail_account"], offer_name)
    if cnt >= REFER_TASKS_NEEDED:
        pay_referral_bonus(uid, friend, cnt)


def settle_friends(candidates):
    """(હમણાં બંધ ચક્ર માટે) ઇનામ બાકી હોય તેવા મિત્રોમાંથી, જેમના અલગ ટાસ્ક મંજૂર છે તેમને ઇનામ આપે."""
    cand = [f for f in candidates
            if f.get("refer_bonus_paid") is not True and f.get("referred_by") and f.get("user_gmail_account")]
    if not cand:
        return 0
    emails = [f["user_gmail_account"] for f in cand]
    done = defaultdict(set)
    for i in range(0, len(emails), 100):
        for d in list_docs(C_TASKS, [q("equal", "user_gmail_account", emails[i:i + 100])]):
            if classify_task_status(d.get("task_status")) == "completed" and counts_for_refer(d.get("offer_taskname"), d.get("task_prize")):
                done[d.get("user_gmail_account")].add(norm(d.get("offer_taskname")))
    paid = 0
    for f in cand:
        n = len(done.get(f["user_gmail_account"], ()))
        if n < REFER_TASKS_NEEDED:
            continue
        try:
            if pay_referral_bonus(f["$id"], f, n):
                paid += 1
        except Exception as e:  # noqa
            log.warning("રેફર ઇનામ તપાસમાં ભૂલ (%s): %s", f.get("user_gmail_account"), e)
    return paid


def settle_referral_bonuses():
    """ધીમું સલામતી ચક્ર (હમણાં બંધ). ફક્ત એવા ખાતા વાંચે જેમને કોઈએ રેફર કર્યા છે અને ઇનામ બાકી છે."""
    try:
        users = list_docs(C_USERS, [q("equal", "refer_bonus_paid", [False]), q("notEqual", "referred_by", [""])])
    except AppwriteError as e:
        log.warning("હળવી શોધ ચાલી નહીં, જૂની રીત વાપરું છું: %s", e)
        users = list_docs(C_USERS, [q("equal", "refer_bonus_paid", [False])])
    return settle_friends(users)


def try_pay_own_referral(user, task_docs, seed=False):
    """મિત્રની પોતાની એપ ટાસ્ક તાજા કરે ત્યારે. શરત પૂરી ન હોય તો કોઈ વધારાનું read નહીં.
    seed=True (એડમિન રિફ્રેશ) હોય તો આ તાજી યાદીથી મંજૂર ટાસ્કના નામની યાદ ફરી બનાવે."""
    try:
        if user.get("refer_bonus_paid") is True or not user.get("referred_by"):
            return
        done = {norm(d.get("offer_taskname")) for d in task_docs
                if classify_task_status(d.get("task_status")) == "completed"
                and counts_for_refer(d.get("offer_taskname"), d.get("task_prize"))}
        if seed:
            with _done_lock:
                _done_offers[user["$id"]] = set(done)
        if len(done) < REFER_TASKS_NEEDED:
            return
        pay_referral_bonus(user["$id"], None, len(done))
    except Exception as e:  # noqa
        log.warning("મિત્રનું રેફર ઇનામ તપાસી શકાયું નહીં: %s", e)


_bg_started = False


def _bg_loop():
    time.sleep(5)
    while True:
        try:
            n = settle_referral_bonuses()
            if n:
                log.info("આ ચક્રમાં %s મિત્રોનું રેફર ઇનામ અપાયું", n)
        except Exception as e:  # noqa
            log.warning("રેફર ઇનામનું ચક્ર નિષ્ફળ: %s", e)
        time.sleep(REFER_CHECK_SECONDS)


def start_background():
    global _bg_started
    if _bg_started:
        return
    _bg_started = True
    threading.Thread(target=_bg_loop, daemon=True, name="referral-settle").start()


# ----------------------------------------------------------------------------
# ભૂલો અને અન્ય
# ----------------------------------------------------------------------------
@app.errorhandler(AppwriteError)
def on_appwrite_error(e):
    log.error("એપરાઈટ ભૂલ: %s", e)
    return err("Server error. Please try again", 502)


@app.errorhandler(413)
def too_large(_):
    return err("Upload is too large", 413)


@app.after_request
def add_headers(resp):
    if request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    if CORS_ORIGIN:
        resp.headers["Access-Control-Allow-Origin"] = CORS_ORIGIN
        resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, X-Admin-Secret"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Allow-Private-Network"] = "true"
    return resp


# ----------------------------------------------------------------------------
# HTML ફાઈલો અને ચિત્રો (public ફોલ્ડરમાંથી)
# ----------------------------------------------------------------------------
APP_PAGES = {"home", "offers", "wallet", "refer", "inviteRefer"}
SAFE_EXT = {".html", ".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico",
            ".ttf", ".woff", ".woff2", ".mp3", ".mp4", ".json", ".txt"}


def real_ip():
    # Render / Cloudflare પાછળ અસલી IP હેડરમાં હોય છે
    ip = request.headers.get("CF-Connecting-IP")
    if not ip:
        ip = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return ip or request.remote_addr or "unknown"


# ખોટા પેજ વારંવાર ખોલનારા IP ને થોડા સમય માટે રોકવા
BAD_HIT_LIMIT = 10        # આટલી ખોટી રિક્વેસ્ટ
BAD_HIT_WINDOW = 60       # આટલા સેકન્ડમાં થાય તો
BAD_BLOCK_SECONDS = 900   # ૧૫ મિનિટ બ્લોક
_bad_hits = defaultdict(list)
_blocked_until = {}


def is_blocked(ip):
    until = _blocked_until.get(ip)
    if until and until > time.time():
        return True
    _blocked_until.pop(ip, None)
    return False


def register_bad_hit(ip):
    now = time.time()
    hits = [t for t in _bad_hits[ip] if now - t < BAD_HIT_WINDOW]
    hits.append(now)
    _bad_hits[ip] = hits
    if len(hits) >= BAD_HIT_LIMIT:
        _blocked_until[ip] = now + BAD_BLOCK_SECONDS
        _bad_hits.pop(ip, None)
    if len(_bad_hits) > 5000:  # યાદ ભરાઈ ન જાય
        _bad_hits.clear()
    if len(_blocked_until) > 5000:
        _blocked_until.clear()


def not_found_page():
    ip = real_ip()
    register_bad_hit(ip)
    msg = ("Access Denied\n\n"
           "This page is restricted. Unauthorized access is prohibited.\n"
           "If you reached this page by mistake, please close it now.")
    return msg, 404, {"Content-Type": "text/plain; charset=utf-8"}


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve(path):
    if is_blocked(real_ip()):
        return ("Too many requests. Try again later.", 429,
                {"Content-Type": "text/plain; charset=utf-8", "Retry-After": str(BAD_BLOCK_SECONDS)})
    if path.startswith("api/"):
        return err("Not found", 404)
    if path and os.path.splitext(path)[1].lower() in SAFE_EXT:
        try:
            resp = send_from_directory(PUBLIC_DIR, path)
            resp.headers["Cache-Control"] = "no-cache"
            return resp
        except NotFound:
            return not_found_page()
    if path == "" or path.split("/")[0] in APP_PAGES:
        try:
            resp = send_from_directory(PUBLIC_DIR, "index.html")
            resp.headers["Cache-Control"] = "no-cache"
            return resp
        except NotFound:
            return not_found_page()
    return not_found_page()


# ----------------------------------------------------------------------------
# ટેલિગ્રામ બોટ - ફક્ત "Telegram channel" ટાસ્ક માટે
#   ક્રમ: CONNECT TELEGRAM -> બોટમાં Start -> બે ચેનલ જોઈન -> Next -> મોબાઇલ નંબર ચકાસણી -> Verify -> ઇનામ
#   - ઇનામ મળે એટલે ઉપનામ, જીમેલ અને રકમ પુરાવાના ગ્રુપમાં મોકલાય છે
#   - માલિક કોડ લખીને બધાને / કોઈ એકને સંદેશ મોકલી શકે છે
# બોટ સર્વર સાથે જ ચાલે છે (ખાસ રસ્તો/વેબહૂક જોઈતો નથી). ટોકન ખાલી હોય તો બોટ ચાલુ થતો નથી.
# ----------------------------------------------------------------------------
# BotFather પાસેથી મળેલો ટોકન (અથવા હોસ્ટિંગમાં TELEGRAM_BOT_TOKEN નામથી મૂકો)
TELEGRAM_BOT_TOKEN = (os.environ.get("TELEGRAM_BOT_TOKEN") or "8826411886:AAFFN5qy_ZMiWToDuhNoHEN72SB73Wvud5U").strip()
# જોડાવી જરૂરી ચેનલો (@ સાથે). બોટને બંનેમાં એડમિન બનાવવો જરૂરી છે, નહીંતર સભ્ય ચકાસી શકાતો નથી
TELEGRAM_CHANNEL = (os.environ.get("TELEGRAM_CHANNEL") or "@cashhfarmer").strip()
TELEGRAM_CHANNELS = [TELEGRAM_CHANNEL, "@CashFarmersProof03"]
# ઓફર યાદીમાં જે ટાસ્કનું નામ છે તે જ (મોટા-નાના અક્ષરનો ફરક પડતો નથી)
TELEGRAM_TASK_NAME = "Telegram channel"
# user_information ટેબલમાં બનાવવાનું ખાનું (Text). index બનાવવાની જરૂર નથી
TG_FIELD = "user_telegram_id"
# ઇનામ જમા થયા પછી ખાતામાં બતાવવાનું લખાણ (એડમિન પેનલના "મંજૂર" જેવું જ)
TG_REWARD_REASON = "Congratulations dear user✅ Task completed, we want to say thank you to you. ❤\u200d🩹🤝"
# પુરાવાનું ગ્રુપ: બોટને ગ્રુપમાં ઉમેરી એડમિન બનાવો, પછી ગ્રુપમાં માલિક /setproof@CashFarmers_03bot લખે એટલે ગ્રુપ સચવાય.
# અથવા અહીં ગ્રુપની id (-100... જેવી) સીધી લખી શકાય.
TELEGRAM_PROOF_CHAT_ID = (os.environ.get("TELEGRAM_PROOF_CHAT_ID") or "").strip()
# True કરો તો ગ્રુપમાં જીમેલ અડધું છુપાઈને જાય (જેમ કે ki****@gmail.com)
TELEGRAM_PROOF_MASK_EMAIL = False

from concurrent.futures import ThreadPoolExecutor as _TGPool
_tg_pool = _TGPool(max_workers=6)     # બે ચેનલ એકસાથે ચકાસવા માટે (ઝડપ)
_tg_pool_outer = _TGPool(max_workers=4)


def tg_api(method, **params):
    """ટેલિગ્રામને સંદેશ મોકલે. ભૂલ થાય તો None (ટોકન ક્યાંય લખાતો નથી)."""
    try:
        r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}", json=params, timeout=45)
        body = r.json()
    except Exception as e:  # noqa
        log.warning("ટેલિગ્રામ %s ચાલ્યું નહીં: %s", method, e.__class__.__name__)
        return None
    if not body.get("ok"):
        log.warning("ટેલિગ્રામ %s: %s", method, str(body.get("description"))[:200])
        return None
    return body.get("result")


def tg_send(chat_id, text, buttons=None, markup=None):
    params = {"chat_id": chat_id, "text": text}
    if markup:
        params["reply_markup"] = markup
    elif buttons:
        params["reply_markup"] = {"inline_keyboard": buttons}
    return tg_api("sendMessage", **params)


def tg_channel_url(channel=None):
    return "https://t.me/" + (channel or TELEGRAM_CHANNEL).lstrip("@")


def tg_join_buttons(styled=True):
    """ઉપર એક લીટીમાં બે ચેનલ (પહેલી લીલી, બીજી વાદળી), નીચે Verify. ટેલિગ્રામ પીળો રંગ આપતું નથી."""
    first = {"text": "🟢 Official Channel", "url": tg_channel_url(TELEGRAM_CHANNELS[0])}
    second = {"text": "🟡 Proof Channel", "url": tg_channel_url(TELEGRAM_CHANNELS[1])}
    if styled:
        first["style"] = "success"   # નવા ટેલિગ્રામમાં લીલું બટન
        second["style"] = "primary"  # નવા ટેલિગ્રામમાં વાદળું બટન
    return [[first, second], [{"text": "✅ Verify", "callback_data": "verify"}]]


def tg_send_join(chat_id, text="📢 Join both channels 👇"):
    """ચેનલ જોડાવાનો ટૂંકો સંદેશ. લીલા રંગની સગવડ ન ચાલે તો રંગ વગર ફરી મોકલે."""
    if tg_send(chat_id, text, tg_join_buttons(True)) is None:
        tg_send(chat_id, text, tg_join_buttons(False))


def tg_user_is_member(tg_id, channel=None):
    """True = ચેનલમાં સભ્ય, False = નથી, None = ચકાસી ન શકાયું (બોટ એડમિન નથી વગેરે)."""
    ch = channel or TELEGRAM_CHANNEL
    body = tg_call("getChatMember", chat_id=ch, user_id=tg_id)
    if not body.get("ok"):
        desc = str(body.get("description"))
        log.warning("ટેલિગ્રામ getChatMember (%s): %s", ch, desc[:200])
        low = desc.lower()
        if "inaccessible" in low or "not found" in low or "rights" in low or "administrator" in low:
            tg_warn_owner(ch)
        return None
    res = body.get("result") or {}
    st = res.get("status")
    if st in ("creator", "administrator", "member"):
        return True
    if st == "restricted":
        return bool(res.get("is_member"))
    return False


def tg_channels_state(tg_id):
    """બધી ચેનલ એકસાથે (સમાંતર) ચકાસે. True = બધીમાં સભ્ય, False = કોઈમાં નથી, None = ચકાસી ન શકાયું."""
    rs = list(_tg_pool.map(lambda ch: tg_user_is_member(tg_id, ch), TELEGRAM_CHANNELS))
    if any(r is False for r in rs):
        return False
    if any(r is None for r in rs):
        return None
    return True


# True = ટેલિગ્રામ જોડાણ (links) અને મોબાઈલ નંબર (phones) ફાઈલમાં સચવાય છે (નકલી ખાતાં રોકવા માટે).
# ટેસ્ટ માટે બંધ કરવું હોય તો False કરો (તે ફક્ત મેમરીમાં રહે, સર્વર ફરી ચાલુ કરતાં ભૂંસાય).
TG_JSON_STORAGE = True

# ટેલિગ્રામ id <-> ખાતાની id નું જોડાણ સર્વરની બાજુની ફાઇલમાં સચવાય છે (ડેટાબેઝમાં index બનાવવાની જરૂર નથી)
TG_LINKS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "telegram_links.json")
_tg_links = {}
_tg_links_lock = threading.Lock()


def _tg_links_load():
    if not TG_JSON_STORAGE:
        return
    try:
        with open(TG_LINKS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            _tg_links.update({str(k): str(v) for k, v in data.items()})
    except FileNotFoundError:
        pass
    except Exception as e:  # noqa
        log.warning("telegram_links.json વાંચી ન શકાઈ: %s", e)


def _tg_links_save():
    if not TG_JSON_STORAGE:
        return
    try:
        tmp = TG_LINKS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_tg_links, f)
        os.replace(tmp, TG_LINKS_FILE)
    except Exception as e:  # noqa
        log.warning("telegram_links.json લખી ન શકાઈ: %s", e)


_tg_links_load()


def tg_uid_for(tg_id):
    """ટેલિગ્રામ id પરથી ખાતાની id. પહેલાં ફાઇલમાં જુએ, ન મળે તો યુઝરોની યાદીમાં user_telegram_id શોધે."""
    key = str(tg_id)
    with _tg_links_lock:
        uid = _tg_links.get(key)
    if uid:
        return uid
    try:
        for d in list_docs(C_USERS):
            if str(d.get(TG_FIELD) or "") == key:
                with _tg_links_lock:
                    _tg_links[key] = d["$id"]
                    _tg_links_save()
                return d["$id"]
    except AppwriteError as e:
        log.warning("ટેલિગ્રામ id થી યુઝર શોધવામાં ભૂલ: %s", e)
    return None


def tg_find_user(tg_id):
    uid = tg_uid_for(tg_id)
    if not uid:
        return None
    try:
        return get_doc(C_USERS, uid)
    except AppwriteError:
        return None


def tg_link_account(tg_id, doc_id):
    """ખાતા (doc_id) સાથે ટેલિગ્રામ જોડે. જવાબ: (યુઝર, કોડ) - કોડ: ok / nouser / taken / already / error"""
    if not re.match(r"^[A-Za-z0-9_\-]{1,64}$", str(doc_id or "")):
        return None, "nouser"
    try:
        user = get_doc(C_USERS, doc_id)
    except AppwriteError as e:
        return None, ("nouser" if e.status == 404 else "error")
    key = str(tg_id)
    other_uid = tg_uid_for(tg_id)
    if other_uid and other_uid != user["$id"]:
        return None, "taken"          # આ ટેલિગ્રામ બીજા ખાતા સાથે જોડાયેલું છે
    with _tg_links_lock:
        for k, v in _tg_links.items():
            if v == user["$id"] and k != key:
                return None, "already"  # આ ખાતું બીજા ટેલિગ્રામ સાથે જોડાયેલું છે
    cur = str(user.get(TG_FIELD) or "")
    if cur and cur != key:
        return None, "already"
    with _tg_links_lock:
        _tg_links[key] = user["$id"]
        _tg_links_save()
    if cur != key:
        try:
            user = update_doc(C_USERS, user["$id"], {TG_FIELD: key})
        except AppwriteError as e:  # ખાનું ન બન્યું હોય તો પણ જોડાણ ફાઇલમાં સચવાયું છે
            log.warning("user_telegram_id ખાનામાં લખી ન શકાયું (ખાનું બનાવ્યું છે?): %s", e)
    return user, "ok"


# મોબાઇલ નંબર ચકાસણી: એક નંબર પર એક જ ખાતાને ઇનામ (નકલી ટેલિગ્રામ ખાતાં બનાવીને ફરી ઇનામ લેવાનું રોકવા)
TELEGRAM_PHONE_PREFIX = "91"  # ફક્ત આ દેશ-કોડ વાળા નંબર ચાલે (ભારત = 91). બધા નંબર ચલાવવા હોય તો ""
TG_PHONES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "telegram_phones.json")
_tg_phones = {}
_tg_phones_lock = threading.Lock()


def _tg_phones_load():
    if not TG_JSON_STORAGE:
        return
    try:
        with open(TG_PHONES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            _tg_phones.update({str(k): str(v) for k, v in data.items()})
    except FileNotFoundError:
        pass
    except Exception as e:  # noqa
        log.warning("telegram_phones.json વાંચી ન શકાઈ: %s", e)


def _tg_phones_save():
    if not TG_JSON_STORAGE:
        return
    try:
        tmp = TG_PHONES_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_tg_phones, f)
        os.replace(tmp, TG_PHONES_FILE)
    except Exception as e:  # noqa
        log.warning("telegram_phones.json લખી ન શકાઈ: %s", e)


_tg_phones_load()


def tg_phone_verified(uid):
    with _tg_phones_lock:
        return any(v == uid for v in _tg_phones.values())


def tg_ask_phone(chat_id):
    tg_send(chat_id, "✅ Channels joined!\n\nNow verify your profile: tap the 📱 button below to share your mobile number. It is used only to stop fake accounts - one number works for one account only.",
            markup={"keyboard": [[{"text": "📱 Share Number", "request_contact": True}]],
                    "resize_keyboard": True, "one_time_keyboard": True})


def tg_handle_contact(tg_id, chat_id, contact):
    if str(contact.get("user_id")) != str(tg_id):
        tg_send(chat_id, "Please share your own number using the 📱 button below.")
        return
    number = re.sub(r"\D", "", str(contact.get("phone_number") or ""))
    if len(number) < 8:
        tg_send(chat_id, "This number is not valid. Please try again.")
        return
    if TELEGRAM_PHONE_PREFIX and not number.startswith(TELEGRAM_PHONE_PREFIX):
        tg_send(chat_id, "Only Indian (+91) numbers are allowed.", markup={"remove_keyboard": True})
        return
    user = tg_find_user(tg_id)
    if not user:
        tg_send(chat_id, "Please tap CONNECT TELEGRAM in the Cash Farmers app first.", markup={"remove_keyboard": True})
        return
    with _tg_phones_lock:
        owner = _tg_phones.get(number)
        if owner and owner != user["$id"]:
            taken = True
        else:
            taken = False
            _tg_phones[number] = user["$id"]
            _tg_phones_save()
    if taken:
        tg_send(chat_id, "This mobile number is already used with another account. One number works for one account only.", markup={"remove_keyboard": True})
        return
    sent = tg_send(chat_id, "✅ Number verified!\n\n⏳ Please wait for your reward...", markup={"remove_keyboard": True})
    verified_msg_id = (sent or {}).get("message_id")
    state = tg_channels_state(tg_id)
    if state is None:
        tg_send_join(chat_id, "Unable to check right now. Please tap Verify again in a moment 👇")
        return
    if state is False:
        tg_send_join(chat_id, "You have not joined both channels yet. Join them, then tap Verify 👇")
        return
    tg_do_reward(chat_id, user, verified_msg_id)


def tg_proof_chat():
    """પુરાવાના ગ્રુપની id (અહીં લખેલી કે /setproof થી સચવાયેલી)."""
    cid = TELEGRAM_PROOF_CHAT_ID
    if not cid:
        try:
            cid = str(_tg_read_json(TG_PROOF_FILE, {}).get("id") or "")
        except Exception:  # noqa
            cid = ""
    if not cid:
        return None
    return int(cid) if cid.lstrip("-").isdigit() else cid


def tg_notify_owner_proof_failed(user_doc, prize, reason):
    """પુરાવો ગ્રુપમાં ન જઈ શક્યો તો માલિકને અંગત સંદેશ મોકલે, જેથી માલિક જાતે પુરાવો મૂકી શકે."""
    try:
        owner = tg_owner_id()
        if not owner:
            log.warning("પુરાવો ન ગયો અને માલિકની id નક્કી નથી, એટલે જાણ થઈ શકી નહીં")
            return
        tg_send(owner, (f"⚠️ Proof NOT posted\n\nReason: {reason}\n\n"
                        f"👤 Nickname: {user_doc.get('user_nickname') or 'User'}\n"
                        f"📧 Gmail: {user_doc.get('user_gmail_account') or ''}\n"
                        f"💰 Reward: ₹{float(prize):.2f}\n📌 Task: {TELEGRAM_TASK_NAME}\n\n"
                        f"Reward was already credited. Please post this proof manually."))
    except Exception as e:  # noqa
        log.warning("માલિકને પુરાવાની નિષ્ફળતાની જાણ ન થઈ શકી: %s", e)


def tg_post_proof(user_doc, prize):
    """ઇનામ મળ્યા પછી ઉપનામ, જીમેલ અને રકમ પુરાવાના ગ્રુપમાં મોકલે.
    નિષ્ફળ જાય તો ૩ વાર પ્રયાસ કરે, છતાં ન જાય તો માલિકને અંગત સંદેશ મોકલે."""
    chat = tg_proof_chat()
    if not chat:
        log.warning("પુરાવાનું ગ્રુપ નક્કી નથી: ગ્રુપમાં /setproof@CashFarmers_03bot લખો")
        tg_notify_owner_proof_failed(user_doc, prize, "Proof group is not set")
        return False
    email = str(user_doc.get("user_gmail_account") or "")
    if TELEGRAM_PROOF_MASK_EMAIL and "@" in email:
        name, dom = email.split("@", 1)
        email = name[:2] + "*" * max(len(name) - 2, 1) + "@" + dom
    text = (f"✅ Reward Credited\n\n👤 Nickname: {user_doc.get('user_nickname') or 'User'}\n"
            f"📧 Gmail: {email}\n💰 Reward: ₹{prize:.2f}\n📌 Task: {TELEGRAM_TASK_NAME}")
    for attempt in range(3):
        if tg_api("sendMessage", chat_id=chat, text=text):
            return True
        if attempt < 2:
            time.sleep(2 * (attempt + 1))   # ૨ સેકન્ડ, પછી ૪ સેકન્ડ રાહ જોઈ ફરી પ્રયાસ
    log.warning("પુરાવો ૩ પ્રયાસ પછી પણ ગ્રુપમાં ન ગયો (%s)", user_doc.get("user_gmail_account"))
    tg_notify_owner_proof_failed(user_doc, prize, "Telegram rejected or failed 3 times (check bot is admin in proof group)")
    return False


def tg_give_reward(user):
    """ઇનામ આપે. જવાબ: ("ok"|"done"|"locked"|"nooffer", રકમ). એક ખાતાને એક જ વાર."""
    uid = user["$id"]
    email = user.get("user_gmail_account") or ""
    offer = None
    for o in cached_offers():
        if norm(o.get("taskName")) == norm(TELEGRAM_TASK_NAME):
            offer = o
            break
    prize = float((offer or {}).get("offer_prize") or 0)
    if not offer or prize <= 0:
        return "nooffer", 0

    with user_lock(uid):
        fresh_f = _tg_pool_outer.submit(get_doc, C_USERS, uid)   # બે વાંચન એકસાથે (ઝડપ)
        tasks_docs = user_tasks(email)
        fresh = fresh_f.result()
        existing = latest_by_offer(tasks_docs).get(norm(offer.get("taskName")))
        st = effective_status(existing) if existing else "unstarted"
        if st == "completed":
            return "done", prize
        if st in ("rejected", "warning"):
            return "locked", prize

        stats = compute_stats(cached_offers(), tasks_docs, [])
        now = ist_now()
        time_str, stamp = time_date_str(now), int(time.time() * 1000)
        if existing and st == "review":
            task, is_new = existing, False      # જૂનો ફોટા વાળો ટાસ્ક રાહ જોતો હોય તો તેને જ મંજૂર કરો
        else:
            data = {
                "user_nickname": fresh.get("user_nickname") or "Unknown User",
                "user_gmail_account": email,
                "user_complete_task": stats["user_complete_task"],
                "user_reject_task": stats["user_rejected_task"],
                "user_pending_task": stats["user_pending_task"] + 1,
                "user_total_task": stats["user_total_task"] + 1,
                "task_prize": prize,
                "task_status": "pending",
                "offer_logo": offer.get("offer_logo") or "",
                "offer_taskname": offer.get("taskName") or "",
                "task_submit_photo": [],
                "task_approval_reason": "",
                "task_timeline": f"{now.day} {now.strftime('%b')} {now.strftime('%H:%M:%S')}",
            }
            try:
                task = create_doc(C_TASKS, data)
            except AppwriteError:
                data["task_submit_photo"] = [tg_channel_url()]  # ખાનું ખાલી ન ચાલે તો ચેનલની લિંક
                task = create_doc(C_TASKS, data)
            is_new = True

        task_id = task["$id"]
        entry_id = "t_" + task_id
        try:
            get_doc(C_HISTORY, entry_id)
            credited = True  # આ ઇનામ પહેલેથી અપાઈ ગયું છે
        except AppwriteError as e:
            if e.status != 404:
                raise
            credited = False
        new_hist, user_doc = None, fresh
        if not credited:
            balance = float(fresh.get("total_balance_available") or 0)
            new_hist = create_doc(C_HISTORY, {
                "user_gmail_account": email,
                "entry_id": entry_id, "type": "reward",
                "title": f"{task.get('offer_taskname') or TELEGRAM_TASK_NAME} Task Reward",
                "amount": float(prize), "status": "success",
                "date": time_str, "timestamp": stamp,
            }, doc_id=entry_id)
            try:
                user_doc = update_doc(C_USERS, uid, {"total_balance_available": round(balance + prize, 2)})
            except Exception:
                try:
                    _call("DELETE", f"/collections/{C_HISTORY}/documents/{entry_id}")
                except Exception as e2:  # noqa
                    log.error("ઇનામની નોંધ પાછી કાઢી શકાઈ નહીં %s: %s", entry_id, e2)
                raise
        task_doc = update_doc(C_TASKS, task_id, {
            "task_status": "success",
            "task_approval_reason": TG_REWARD_REASON,
        })

    # બાકીનું કામ પાછળ ચાલે, જેથી યુઝરને Verify નો જવાબ તરત મળે
    def after():
        try:
            if not cache_replace_task(email, task_doc):
                forget_user_cache(email, "tasks")
            if new_hist is not None:
                cache_add_history(email, new_hist)
            save_user_stats(user_doc, {
                "user_complete_task": stats["user_complete_task"] + 1,
                "user_rejected_task": stats["user_rejected_task"],
                "user_pending_task": stats["user_pending_task"] + (0 if is_new else -1),
                "user_total_task": stats["user_total_task"] + (1 if is_new else 0),
            })
        except Exception as e:  # noqa
            log.warning("ટેલિગ્રામ ઇનામ પછી યાદી/આંકડા બદલવામાં ભૂલ: %s", e)
        try:
            tg_post_proof(user_doc, prize)
        except Exception as e:  # noqa
            log.warning("પુરાવાના ગ્રુપમાં મોકલી ન શકાયું: %s", e)
            tg_notify_owner_proof_failed(user_doc, prize, f"Unexpected error: {e.__class__.__name__}")
        # [નવું] મિત્રના અલગ ૩ ઓફર પૂરા થયા હોય તો રેફર ઇનામ (યાદમાં ગણતરી)
        try:
            referral_progress(uid, fresh, task.get("offer_taskname") or TELEGRAM_TASK_NAME, prize)
        except Exception as e:  # noqa
            log.warning("ટેલિગ્રામ ઇનામ પછી રેફર ઇનામ તપાસમાં ભૂલ (%s): %s", email, e)
        # ખુલ્લી એપને તરત મોકલો (સર્વરની એપ માટે)
        try:
            payload = dict(user_push_basics(user_doc))
            payload["tasks"] = [pick(task_doc, TASK_FIELDS)]
            if new_hist is not None:
                payload["entries"] = [pick(new_hist, HISTORY_FIELDS)]
            push_user(uid, payload)
        except Exception as e:  # noqa
            log.warning("ટેલિગ્રામ ઇનામ પછી એપને તરત મોકલી ન શકાયું: %s", e)

    threading.Thread(target=after, daemon=True, name="telegram-after-reward").start()
    return "ok", prize


def tg_do_reward(chat_id, user, delete_msg_id=None):
    """ઇનામ આપી યુઝરને સંદેશ મોકલે. delete_msg_id આપ્યો હોય તો ઇનામનો સંદેશ ગયા પછી તે સંદેશ (નંબર ચકાસાયાનો) કાઢી નાખે."""
    try:
        result, prize = tg_give_reward(user)
    except Exception as e:  # noqa
        log.warning("ટેલિગ્રામ ઇનામ આપવામાં ભૂલ: %s", e)
        tg_send_join(chat_id, "Something went wrong. Please tap Verify again in a moment 👇")
        return
    if result == "ok":
        tg_send(chat_id, f"🎉 Verified! ₹{prize:.2f} has been credited to your account.\n\nGo back to the Cash Farmers app. 🙏")
    elif result == "done":
        tg_send(chat_id, "You have already received the reward for this task.")
    elif result == "locked":
        tg_send(chat_id, "This task is locked right now. Please try later.")
    else:
        tg_send(chat_id, "This task is not available right now.")
    if delete_msg_id:
        tg_api("deleteMessage", chat_id=chat_id, message_id=delete_msg_id)


def tg_handle_callback(kind, tg_id, chat_id, cb_id):
    """Verify બટન (જૂના સંદેશમાં "next" બટન હોય તો તે પણ આ જ રીતે ચાલે)."""
    # બટનનો જવાબ સૌથી પહેલા તરત આપી દો (ધીમા નેટ પર મોડું થાય તો "query is too old" આવે છે)
    tg_api("answerCallbackQuery", callback_query_id=cb_id)

    state_f = _tg_pool_outer.submit(tg_channels_state, tg_id)   # ચેનલ ચકાસણી અને યુઝર શોધ એકસાથે
    user = tg_find_user(tg_id)
    state = state_f.result()
    if not user:
        tg_send(chat_id, "Please tap CONNECT TELEGRAM in the Cash Farmers app first.")
        return
    if state is None:
        tg_send_join(chat_id, "Unable to check your channels right now. Please try again in a moment 👇")
        return
    if state is False:
        tg_send_join(chat_id, "You have not joined both channels yet. Join them, then tap Verify 👇")
        return
    if not tg_phone_verified(user["$id"]):
        tg_ask_phone(chat_id)      # નંબર હજી ચકાસ્યો નથી: પહેલાં નંબર માગો, પછી ઇનામ આપોઆપ
        return
    tg_do_reward(chat_id, user)


# ----------------------------------------------------------------------------
# બોટ માલિકના સંદેશા: લખાણ પછી ગુપ્ત કોડ લખો તો
#   (kinjulov3jack)  -> બોટ શરૂ કરનાર બધાને સંદેશ જાય
#   (jack)love       -> કોઈના સંદેશ પર Reply કરીને લખો તો ફક્ત તેને અંગત ચેટમાં જાય
# કોડ સામેવાળાને જતા સંદેશમાં ક્યારેય આવતો નથી (કાપી નાખીને મોકલાય છે) અને તમારી ચેટમાંથી
# કોડ વાળો મૂળ સંદેશ મોકલ્યા પછી કાઢી નખાય છે. માલિકને જવાબો ગુજરાતીમાં આવે છે.
# ----------------------------------------------------------------------------
TELEGRAM_BROADCAST_CODE = "(kinjulov3jack)"
TELEGRAM_REPLY_CODE = "(jack)love"
# માલિકની ટેલિગ્રામ id. ખાલી (0) હોય તો જે પહેલી વાર સાચો કોડ લખે તે માલિક ગણાય અને id ફાઇલમાં સચવાય.
# બોટમાં /id લખશો તો તમારી id મળશે.
try:
    TELEGRAM_OWNER_ID = int(os.environ.get("TELEGRAM_OWNER_ID") or 0)
except ValueError:
    TELEGRAM_OWNER_ID = 0

TG_OWNER_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "telegram_owner.json")
TG_CHATS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "telegram_chats.json")
TG_FWD_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "telegram_forwards.json")
TG_PROOF_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "telegram_proof.json")
_tg_owner_lock = threading.Lock()
_tg_chats = set()
_tg_fwd = {}  # માલિકને forward થયેલા સંદેશની id -> તે યુઝરની ચેટ id


def _tg_read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except Exception as e:  # noqa
        log.warning("%s વાંચી ન શકાઈ: %s", os.path.basename(path), e)
        return default


def _tg_write_json(path, obj):
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f)
        os.replace(tmp, path)
    except Exception as e:  # noqa
        log.warning("%s લખી ન શકાઈ: %s", os.path.basename(path), e)


_tg_chats.update(int(x) for x in _tg_read_json(TG_CHATS_FILE, []) if str(x).lstrip("-").isdigit())
_tg_chats.update(int(k) for k in list(_tg_links) if str(k).isdigit())   # જે યુઝર ખાતું જોડી ચૂક્યા છે તેમને પણ
_tg_fwd.update({str(k): int(v) for k, v in _tg_read_json(TG_FWD_FILE, {}).items()})


def tg_owner_id():
    if TELEGRAM_OWNER_ID:
        return TELEGRAM_OWNER_ID
    try:
        return int(_tg_read_json(TG_OWNER_FILE, {}).get("id") or 0)
    except (TypeError, ValueError):
        return 0


def tg_note_chat(chat_id):
    """બોટ શરૂ કરનાર/લખનારની ચેટ યાદ રાખે (બધાને સંદેશ મોકલવા માટે)."""
    if chat_id is None:
        return
    with _tg_owner_lock:
        if chat_id not in _tg_chats:
            _tg_chats.add(chat_id)
            _tg_write_json(TG_CHATS_FILE, sorted(_tg_chats))


def tg_call(method, **params):
    """tg_api જેવું પણ આખો જવાબ (ભૂલના કોડ સાથે) પાછો આપે."""
    try:
        r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}", json=params, timeout=45)
        return r.json()
    except Exception as e:  # noqa
        return {"ok": False, "error_code": 0, "description": e.__class__.__name__}


def tg_split_code(raw, code):
    """લખાણ code થી પૂરું થતું હોય તો code વગરનું લખાણ આપે, નહીંતર None. {code} પણ ચાલે."""
    t = str(raw or "").rstrip()
    for variant in ("{" + code + "}", code):
        if t.endswith(variant):
            return t[: len(t) - len(variant)].rstrip()
    return None


def tg_trim_entities(entities, body):
    n = len(body.encode("utf-16-le")) // 2
    return [e for e in (entities or []) if e.get("offset", 0) + e.get("length", 0) <= n]


def tg_deliver(target, msg, body, is_text):
    """code વગરનો સંદેશ target ને મોકલે (લખાણ કે ફોટો/વિડિયો + લખાણ). જવાબ: Telegram નો જવાબ."""
    if is_text:
        params = {"chat_id": target, "text": body}
        ents = tg_trim_entities(msg.get("entities"), body)
        if ents:
            params["entities"] = ents
        method = "sendMessage"
    else:
        params = {"chat_id": target, "from_chat_id": msg["chat"]["id"], "message_id": msg["message_id"], "caption": body}
        ents = tg_trim_entities(msg.get("caption_entities"), body)
        if ents:
            params["caption_entities"] = ents
        method = "copyMessage"
    res = tg_call(method, **params)
    if not res.get("ok") and res.get("error_code") == 429:
        time.sleep(int((res.get("parameters") or {}).get("retry_after") or 3) + 1)
        res = tg_call(method, **params)
    return res


def tg_preview(body, is_text):
    return ("\n\nસંદેશ:\n" + body[:300]) if (is_text and body) else ""


def tg_broadcast(owner_chat, msg, body, is_text):
    with _tg_owner_lock:
        targets = [c for c in _tg_chats if c != owner_chat]
    ok = fail = 0
    for cid in targets:
        res = tg_deliver(cid, msg, body, is_text)
        if res.get("ok"):
            ok += 1
        else:
            fail += 1
            if res.get("error_code") == 403 or "chat not found" in str(res.get("description")):
                with _tg_owner_lock:           # બોટ બંધ/બ્લૉક કરનારને યાદીમાંથી કાઢો
                    _tg_chats.discard(cid)
                    _tg_write_json(TG_CHATS_FILE, sorted(_tg_chats))
        time.sleep(0.05)
    tg_send(owner_chat, f"📢 મોકલવાનું પૂરું થયું: {ok} લોકોને ગયો, {fail} લોકોને ન ગયો." + tg_preview(body, is_text))
    tg_api("deleteMessage", chat_id=owner_chat, message_id=msg["message_id"])   # કોડ વાળો મૂળ સંદેશ કાઢી નાખો


def tg_forward_to_owner(msg):
    """યુઝરનો સંદેશ માલિકને forward કરે, જેથી માલિક Reply કરી શકે. માલિક ખબર ન હોય તો False."""
    owner = tg_owner_id()
    if not owner:
        return False
    res = tg_api("forwardMessage", chat_id=owner, from_chat_id=msg["chat"]["id"], message_id=msg["message_id"])
    if res is None:
        return False
    with _tg_owner_lock:
        _tg_fwd[str(res["message_id"])] = msg["chat"]["id"]
        while len(_tg_fwd) > 3000:
            _tg_fwd.pop(next(iter(_tg_fwd)))
        _tg_write_json(TG_FWD_FILE, _tg_fwd)
    return True


def tg_handle_owner(msg, chat_id, tg_id):
    """માલિકનો કોડ વાળો સંદેશ હોય તો સંભાળે અને True આપે; બાકી False."""
    is_text = msg.get("text") is not None
    raw = msg.get("text") if is_text else msg.get("caption")
    if not raw:
        return False
    b_body = tg_split_code(raw, TELEGRAM_BROADCAST_CODE)
    r_body = None if b_body is not None else tg_split_code(raw, TELEGRAM_REPLY_CODE)
    if b_body is None and r_body is None:
        return False
    owner = tg_owner_id()
    if owner and owner != tg_id:
        return False                        # બીજાનો સંદેશ સામાન્ય સંદેશ ગણાય
    if not owner:
        _tg_write_json(TG_OWNER_FILE, {"id": tg_id})
        tg_send(chat_id, "✅ તમે બોટના માલિક તરીકે સચવાયા.")
    body = b_body if b_body is not None else r_body
    if not body and is_text:
        tg_send(chat_id, "કોડની આગળ સંદેશ લખો.")
        return True
    if b_body is not None:
        threading.Thread(target=tg_broadcast, args=(chat_id, msg, body, is_text), daemon=True).start()
        tg_send(chat_id, "📤 બધાને મોકલવાનું શરૂ કર્યું...")
        return True
    reply = msg.get("reply_to_message")
    if not reply:
        tg_send(chat_id, "જેને જવાબ આપવો હોય તેના સંદેશ પર Reply કરીને લખો.")
        return True
    with _tg_owner_lock:
        target = _tg_fwd.get(str(reply.get("message_id")))
    if not target:
        tg_send(chat_id, "આ સંદેશનો યુઝર મળ્યો નથી. ફક્ત બોટે મોકલેલા (આગળ મોકલેલા) સંદેશ પર Reply કરો.")
        return True
    res = tg_deliver(target, msg, body, is_text)
    tg_send(chat_id, ("✅ અંગત સંદેશ મોકલ્યો." if res.get("ok") else "❌ સંદેશ ગયો નહીં (યુઝરે બોટ બ્લૉક કર્યો હશે).") + tg_preview(body, is_text))
    if res.get("ok"):
        tg_api("deleteMessage", chat_id=chat_id, message_id=msg["message_id"])   # કોડ વાળો મૂળ સંદેશ કાઢી નાખો
    return True


def tg_handle_group(msg, chat):
    """પુરાવાનું ગ્રુપ સાચવે. બોટ ગ્રુપમાં એડમિન હોય અને માલિક તે ગ્રુપમાં કંઈ પણ લખે એટલે ગ્રુપ સચવાય
    (ચેનલ સચવાયેલી હોય કે કંઈ ન સચવાયું હોય તો). બીજું ગ્રુપ બદલવું હોય તો ત્યાં માલિક /setproof લખે."""
    text = str(msg.get("text") or "").strip().lower()
    is_cmd = text.startswith("/setproof")
    sender = (msg.get("from") or {}).get("id")
    kind = "channel" if chat.get("type") == "channel" else "group"
    if kind == "channel":                  # ચેનલમાં ફક્ત એડમિન લખી શકે
        if is_cmd:
            _tg_write_json(TG_PROOF_FILE, {"id": chat["id"], "type": "channel"})
            tg_send(chat["id"], "✅ આ ચેનલ ઇનામના પુરાવા માટે સચવાઈ. હવેથી ઇનામની માહિતી અહીં આવશે.")
        return
    owner = tg_owner_id()
    if not owner or owner != sender:
        if is_cmd:
            tg_send(chat["id"], "આ આદેશ ફક્ત બોટના માલિક વાપરી શકે. પહેલા બોટમાં માલિકનો કોડ લખો.")
        return
    saved = _tg_read_json(TG_PROOF_FILE, {})
    if is_cmd or not saved.get("id") or saved.get("type") != "group":
        _tg_write_json(TG_PROOF_FILE, {"id": chat["id"], "type": "group"})
        tg_send(chat["id"], "✅ આ ગ્રુપ ઇનામના પુરાવા માટે સચવાયું. હવેથી ઇનામની માહિતી અહીં આવશે.")


def tg_handle_update(upd):
    msg = upd.get("message") or upd.get("channel_post")
    if msg:
        chat = msg.get("chat") or {}
        if chat.get("type") != "private":
            tg_handle_group(msg, chat)
            return
        chat_id = chat.get("id")
        tg_id = (msg.get("from") or {}).get("id")
        text = str(msg.get("text") or "").strip()
        if tg_owner_id() != tg_id:
            tg_note_chat(chat_id)
        if msg.get("contact"):
            tg_handle_contact(tg_id, chat_id, msg.get("contact"))
            return
        if tg_handle_owner(msg, chat_id, tg_id):
            return
        if text.lower().startswith("/id"):
            tg_send(chat_id, f"Your Telegram id: {tg_id}")
            return
        if not text.startswith("/start"):
            if tg_owner_id() == tg_id:
                return
            if not tg_forward_to_owner(msg):
                tg_send(chat_id, "Please tap CONNECT TELEGRAM in the Telegram task of the Cash Farmers app.")
            return
        parts = text.split(maxsplit=1)
        payload = parts[1].strip() if len(parts) > 1 else ""
        if not payload:
            tg_send(chat_id, "Hello! 👋\nPlease open the Cash Farmers app, go to the Telegram task and tap CONNECT TELEGRAM first.")
            return
        user, code = tg_link_account(tg_id, payload)
        if code == "ok":
            tg_send_join(chat_id)
        elif code == "taken":
            tg_send(chat_id, "This Telegram account is already linked to another Cash Farmers account. One Telegram works for one account only.")
        elif code == "already":
            tg_send(chat_id, "This Cash Farmers account is already linked to another Telegram account.")
        elif code == "nouser":
            tg_send(chat_id, "This link is not valid. Please tap CONNECT TELEGRAM in the app again.")
        else:
            tg_send(chat_id, "Something went wrong. Please try again in a moment.")
        return
    cq = upd.get("callback_query")
    if cq and cq.get("data") in ("next", "verify"):
        chat_id = ((cq.get("message") or {}).get("chat") or {}).get("id") or (cq.get("from") or {}).get("id")
        tg_handle_callback(cq.get("data"), (cq.get("from") or {}).get("id"), chat_id, cq.get("id"))


def telegram_bot_loop():
    tg_api("deleteWebhook")  # જૂનો વેબહૂક હોય તો બંધ, નહીંતર સંદેશ આવતા નથી
    log.info("ટેલિગ્રામ બોટ ચાલુ થયો (ચેનલો: %s)", ", ".join(TELEGRAM_CHANNELS))
    offset = None
    while True:
        params = {"timeout": 30, "allowed_updates": ["message", "callback_query", "channel_post"]}
        if offset:
            params["offset"] = offset
        updates = tg_api("getUpdates", **params)
        if updates is None:
            time.sleep(5)
            continue
        for upd in updates:
            offset = upd["update_id"] + 1
            # દરેક અપડેટ અલગ થ્રેડમાં, જેથી એક ધીમું કામ બીજા યુઝરને રોકે નહીં (Verify ઝડપી રહે)
            threading.Thread(target=_tg_safe_handle, args=(upd,), daemon=True).start()


def _tg_safe_handle(upd):
    try:
        tg_handle_update(upd)
    except Exception as e:  # noqa
        log.warning("ટેલિગ્રામ સંદેશમાં ભૂલ: %s", e)


if TELEGRAM_BOT_TOKEN:
    threading.Thread(target=telegram_bot_loop, daemon=True, name="telegram-bot").start()


# યુઝર કંઈ ન કરે ત્યારે સર્વર જાતે ડેટાબેઝ ન વાંચે એટલે પાછળનું ચક્ર બંધ
os.environ.setdefault("NO_BACKGROUND", "1")
if not os.environ.get("NO_BACKGROUND"):
    start_background()


if __name__ == "__main__":
    log.info("HTML ફોલ્ડર: %s", PUBLIC_DIR)
    if not os.path.isfile(os.path.join(PUBLIC_DIR, "index.html")):
        log.warning("આ ફોલ્ડરમાં index.html મળી નથી! PUBLIC_FOLDER માં સાચું સરનામું લખો.")
    app.run(host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", 5000)), threaded=True)
