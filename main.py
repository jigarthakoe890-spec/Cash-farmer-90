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
from flask import Flask, g, jsonify, request, send_from_directory
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
IMGBB_API_KEY = ""

# લોગિન ટોકન સાચા છે કે નકલી તે ચકાસવા માટેનું ગુપ્ત લખાણ (મેં બનાવી આપ્યું છે, બદલવું જરૂરી નથી)
SECRET_KEY = "1cee97246f1da3872c21ce3601ae4706aa484f93bb5ad6ec8d21ba0e616d4dc9"

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

# રેફરલ ઇનામ (લેવલ પ્રમાણે) અને જરૂરી ટાસ્ક (મિત્રના અલગ અલગ ઓફર મંજૂર થયા હોવા જોઈએ)
REFER_REWARDS = {1: 40, 2: 10, 3: 3}
REFER_TASKS_NEEDED = 2
REFER_CHECK_SECONDS = 1800  # બધાને તપાસતું ધીમું ચક્ર (સલામતી માટે, ૩૦ મિનિટ). ઝડપી ઇનામ નીચેની લક્ષિત તપાસથી મળે છે
REFER_ONLINE_CHECK_SECONDS = 300  # રેફર કરનારની એપ ખુલ્લી હોય ત્યારે તેના મિત્રો આટલા સેકન્ડે વધુમાં વધુ એક વાર તપાસાય
OFFERS_CACHE_SECONDS = 21600  # ઓફરોની યાદી સર્વર આટલા સેકન્ડ (૬ કલાક) યાદ રાખે (reads બચાવવા). નવી ઓફર તરત બતાવવી હોય તો સર્વર ફરી ચાલુ કરો
USER_CACHE_SECONDS = 90  # વપરાશકર્તાના ટાસ્ક અને ઇતિહાસની યાદી સર્વર આટલા સેકન્ડ યાદ રાખે (ફક્ત સ્ક્રીન બતાવવા માટે)
AUTH_CACHE_SECONDS = 30  # [નવું] લોગિન ચકાસવા માટે યુઝરની રો સર્વર આટલા સેકન્ડ યાદ રાખે (દરેક કોલે ફરી ન વાંચે)
REFERRALS_CACHE_SECONDS = 300  # [નવું] રેફર યાદી સર્વર આટલા સેકન્ડ (૫ મિનિટ) યાદ રાખે
STATS_SYNC_MIN_SECONDS = 300  # એક વપરાશકર્તાના આંકડા /api/sync-stats થી આટલા સેકન્ડે એક જ વાર ગણાય

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


_auth_cache = {}        # [નવું] યુઝર id -> (સમય, રો)
_auth_dropped = {}      # [નવું] યુઝર id -> છેલ્લે ક્યારે ભૂંસ્યું
_referrals_cache = {}   # [નવું] યુઝર id -> { (લેવલ, limit, offset, counts): (સમય, જવાબ) }
_aux_lock = threading.Lock()


def drop_user_caches(uid):
    """[નવું] યુઝરની રોમાં કંઈ પણ લખાય ત્યારે તેનું યાદ રાખેલું (રો અને રેફર યાદી) તરત ભૂંસો."""
    now = time.time()
    with _aux_lock:
        _auth_cache.pop(uid, None)
        _referrals_cache.pop(uid, None)
        _auth_dropped[uid] = now


def update_doc(col, doc_id, data):
    res = _call("PATCH", f"/collections/{col}/documents/{doc_id}", json={"data": data})
    if col == C_USERS:
        drop_user_caches(doc_id)  # [નવું]
    return res


def pick(doc, keys):
    return {k: doc.get(k) for k in keys if k in doc}


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
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
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
    """જૂના (સીધા લખાણ) પાસવર્ડ ચાલશે અને સફળ લોગિન પછી આપોઆપ કોડેડ થઈ જશે."""
    stored = str(user.get("user_password") or "")
    if not stored:
        return False
    if is_hashed(stored):
        return check_password_hash(stored, given)
    if not hmac.compare_digest(stored.encode("utf-8"), given.encode("utf-8")):
        return False
    try:
        update_doc(C_USERS, user["$id"], {"user_password": generate_password_hash(given, method="pbkdf2:sha256")})
    except AppwriteError as e:
        log.warning("પાસવર્ડ કોડેડ કરી શકાયો નહીં (user_password ખાનાની લંબાઈ ૨૫૫ કરો): %s", e)
    return True


def make_token(user):
    return serializer.dumps({"id": user["$id"], "email": user["user_gmail_account"]})


def get_user_for_auth(uid):
    """[નવું] યુઝરની રો થોડી વાર યાદ રાખે. કોઈ ફેરફાર લખાય ત્યારે આપોઆપ ભૂંસાય છે."""
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
            user = get_user_for_auth(data["id"])  # [નવું] પહેલાં: get_doc(C_USERS, data["id"])
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
# ટાસ્કની સ્થિતિ અને આંકડા (HTML ના જૂના હિસાબ જેવા જ)
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
        "user_reject_task": reject,
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
    """[નવું] ઇતિહાસનું ફક્ત એક પાનું (નવી નોંધ પહેલાં). બધી નોંધ એકસાથે વાંચતું નથી."""
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
            if kind == "history":  # [નવું] પાનાં પ્રમાણે યાદ રાખેલી પહેલી યાદી પણ ભૂંસો
                _user_cache.pop(("history_p1", email), None)
                _user_cache_dropped[("history_p1", email)] = now


_last_stats_sync = {}


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


# ----------------------------------------------------------------------------
# [નવું] ગણતરી પહેલેથી તૈયાર: કંઈ બને ત્યારે જ આંકડા બદલાય, વારંવાર બધું વાંચીને ગણવું નહીં
# ----------------------------------------------------------------------------
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
            "user_complete_task", "user_pending_task", "user_reject_task", "user_total_task")})
    except Exception as e:  # noqa
        log.warning("આંકડા અપડેટ ન થયા: %s", e)


# ----------------------------------------------------------------------------
# રેફરલ કોડ
# ----------------------------------------------------------------------------
def generate_refer_code():
    caps, smalls, nums = string.ascii_uppercase, string.ascii_lowercase, string.digits
    return random.choice(caps) + random.choice(caps) + random.choice(smalls) + random.choice(nums) + random.choice(smalls)


def ensure_refer_code(user):
    if user.get("user_refer_code"):
        return user["user_refer_code"]
    while True:
        code = generate_refer_code()
        if not find_one(C_USERS, "user_refer_code", code):
            break
    update_doc(C_USERS, user["$id"], {"user_refer_code": code, "user_refer_link": f"{INVITE_BASE}{code}"})
    return code


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

        level2 = (referrer.get("referred_by") or "") if referrer else ""
        level3 = (referrer.get("referred_by_level2") or "") if referrer else ""

        create_doc(C_USERS, {
            "user_nickname": nickname,
            "user_gmail_account": email,
            "user_password": generate_password_hash(password, method="pbkdf2:sha256"),
            "referred_by": refer_code,
            "referred_by_level2": level2,
            "referred_by_level3": level3,
            "refer_bonus_paid": False,
        })

    # ઉપરના ૩ લેવલને નવા સભ્યની જાણ (જૂના કોડ જેવું જ)
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    targets = []
    if referrer:
        targets.append(referrer["$id"])
    for code in (level2, level3):
        if code:
            try:
                doc = find_one(C_USERS, "user_refer_code", code)
                if doc:
                    targets.append(doc["$id"])
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
    # [નવું] પાનાં પ્રમાણે: /api/history?limit=30&offset=0. limit ન આપો તો જૂની રીત (બધી નોંધ) જ ચાલે.
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
        refresh_task_stats_from_cache(g.user)  # [નવું] યાદ રાખેલી યાદી પરથી જ, નવું વાંચન નહીં
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

        stats = compute_stats(cached_offers(), tasks_docs, [])  # [નવું] ઇતિહાસ વાંચવો નહીં, ટાસ્કના આંકડા ટાસ્ક પરથી જ
        now = ist_now()
        timeline = f"{now.day} {now.strftime('%b')} {now.strftime('%H:%M:%S')}"

        create_doc(C_TASKS, {
            "user_nickname": user.get("user_nickname") or "Unknown User",
            "user_gmail_account": email,
            "user_complete_task": stats["user_complete_task"],
            "user_reject_task": stats["user_reject_task"],
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
        forget_user_cache(email, "tasks")

    # [નવું] બધું ફરી વાંચીને ગણવાને બદલે, હમણાં જ ગણેલા આંકડા (+1 સાથે) યુઝર રોમાં લખી દો
    save_user_stats(user, {
        "user_complete_task": stats["user_complete_task"],
        "user_reject_task": stats["user_reject_task"],
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
        except AppwriteError as e:
            log.error("ઇતિહાસની નોંધ ન થઈ: %s", e)
        forget_user_cache(email, "history")

    # [નવું] ઉપાડની ગણતરી ઉપર થઈ ગઈ છે (counts), એ જ યુઝર રોમાં લખો. ટાસ્ક અને ઇતિહાસ ફરી વાંચવા નહીં
    save_user_stats(user, {
        "user_total_withdraw": counts[0],
        "user_total_successwithdraw": counts[1],
        "user_total_rejectedwithdraw": counts[2],
        "user_total_pendingwithdraw": counts[3],
    })
    return jsonify({"balance": new_balance, "entry": entry, "fee": fee, "net": net})


# ----------------------------------------------------------------------------
# રેફરલ (લેવલ ૧, ૨, ૩)
# ----------------------------------------------------------------------------
def ref_cache_get(uid, key):
    with _aux_lock:
        hit = _referrals_cache.get(uid, {}).get(key)
    if hit and time.time() - hit[0] < REFERRALS_CACHE_SECONDS:
        return hit[1]
    return None


def ref_cache_put(uid, key, payload, started):
    with _aux_lock:
        if _auth_dropped.get(uid, 0) < started:  # આ દરમિયાન ફેરફાર લખાયો હોય તો જૂનું ન સાચવવું
            if len(_referrals_cache) > 2000:
                _referrals_cache.clear()
            d = _referrals_cache.setdefault(uid, {})
            if len(d) > 40:
                d.clear()
            d[key] = (started, payload)


# [નવું] રેફર યાદી ટુકડામાં: સર્વર ફક્ત માંગેલા ટુકડા જેટલા જ મિત્રો ડેટાબેઝમાંથી વાંચે છે.
# લેવલ 1 = referred_by, લેવલ 2 = referred_by_level2, લેવલ 3 = referred_by_level3 (ખાતું બનાવતી વખતે ભરાય છે).
# લેવલ 0 = ત્રણેય લેવલ ભેગા, સૌથી નવા પહેલાં.
_fast_downline_ok = True
_slow_downline_cache = {}   # રેફર કોડ -> (સમય, (l1, l2, l3))  [ફક્ત જૂની ધીમી રીત માટે]


def _level_of(doc, code):
    if doc.get("referred_by") == code:
        return 1
    if doc.get("referred_by_level2") == code:
        return 2
    return 3


def _downline_filter(code, level):
    if level == 1:
        return [q("equal", "referred_by", [code])]
    if level == 2:
        return [q("equal", "referred_by_level2", [code])]
    if level == 3:
        return [q("equal", "referred_by_level3", [code])]
    return [json.dumps({"method": "or", "values": [
        {"method": "equal", "attribute": "referred_by", "values": [code]},
        {"method": "equal", "attribute": "referred_by_level2", "values": [code]},
        {"method": "equal", "attribute": "referred_by_level3", "values": [code]},
    ]})]


def _list_page(queries):
    return _call("GET", f"/collections/{C_USERS}/documents", params={"queries[]": queries})


def _total_of(res):
    t_ = res.get("total")
    return t_ if isinstance(t_, int) else len(res.get("documents", []))


def downline_all_slow(code):
    """જૂની રીત (બધા મિત્રો વાંચે). ફક્ત ત્યારે વપરાય જો ઝડપી રીત ન ચાલે."""
    hit = _slow_downline_cache.get(code)
    if hit and time.time() - hit[0] < REFERRALS_CACHE_SECONDS:
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


def load_refer_page(code, level, limit, offset, want_counts):
    """પાછું આપે: ([(લેવલ, રો), ...], હજુ બાકી છે કે નહીં, કુલ સંખ્યાઓ કે None, સફળ ઇનામ સંખ્યા કે None)"""
    global _fast_downline_ok
    if _fast_downline_ok:
        try:
            res = _list_page(_downline_filter(code, level) + [
                q("orderDesc", "$createdAt"), q("limit", values=[limit]), q("offset", values=[offset])])
            docs = res.get("documents", [])
            total = res.get("total")
            has_more = (offset + len(docs) < total) if isinstance(total, int) else len(docs) >= limit
            page = [(level or _level_of(d, code), d) for d in docs]
            counts = paid = None
            if want_counts:
                counts = {}
                for n in (1, 2, 3):
                    counts[str(n)] = _total_of(_list_page(_downline_filter(code, n) + [q("limit", values=[1])]))
                paid = _total_of(_list_page(_downline_filter(code, 0) + [
                    q("equal", "refer_bonus_paid", [True]), q("limit", values=[1])]))
            return page, has_more, counts, paid
        except AppwriteError as e:
            if e.status != 400:
                raise
            _fast_downline_ok = False
            log.warning("ઝડપી રેફર શોધ ચાલી નહીં, જૂની રીત વાપરું છું. એપરાઈટમાં user_information ટેબલ પર "
                        "referred_by_level2 અને referred_by_level3 ના index બનાવો: %s", e)

    l1, l2, l3 = downline_all_slow(code)
    pairs = [(1, d) for d in l1] + [(2, d) for d in l2] + [(3, d) for d in l3]
    chosen = pairs if level == 0 else [p_ for p_ in pairs if p_[0] == level]
    chosen.sort(key=lambda p_: p_[1].get("$createdAt") or "", reverse=True)
    page = chosen[offset:offset + limit]
    has_more = offset + len(page) < len(chosen)
    counts = {"1": len(l1), "2": len(l2), "3": len(l3)} if want_counts else None
    paid = sum(1 for _, d in pairs if d.get("refer_bonus_paid") is True) if want_counts else None
    return page, has_more, counts, paid


@app.get("/api/referrals")
@auth_required
def referrals():
    # [નવું] /api/referrals?level=0|1|2|3&limit=10&offset=0&counts=1
    user = g.user
    code = ensure_refer_code(user)
    uid = user["$id"]

    level = safe_int(request.args.get("level"))
    if level not in (0, 1, 2, 3):
        level = 0
    limit = max(1, min(50, safe_int(request.args.get("limit")) or 10))
    offset = max(0, safe_int(request.args.get("offset")))
    want_counts = request.args.get("counts") == "1"

    key = (level, limit, offset, want_counts)
    started = time.time()
    cached = ref_cache_get(uid, key)
    if cached is not None:
        return jsonify(cached)

    page, has_more, counts, paid = load_refer_page(code, level, limit, offset, want_counts)

    # ઇનામ બાકી હોય તેવા, ફક્ત હમણાં બતાવાતા મિત્રોમાંથી જેમના ૨ ટાસ્ક થઈ ગયા હોય તેમને જ તપાસે
    if settle_downline(uid, [d for _, d in page]):
        _slow_downline_cache.pop(code, None)
        page, has_more, counts, paid = load_refer_page(code, level, limit, offset, want_counts)
        user = get_doc(C_USERS, uid)

    # "Success Refer" સંખ્યા (કુલ સફળ ઇનામ) - બધા મિત્રો વાંચ્યા વગર ગણેલી
    if paid is not None and safe_int(user.get("user_refer_number")) != paid:
        try:
            update_doc(C_USERS, uid, {"user_refer_number": paid})
        except AppwriteError:
            pass
    refer_number = paid if paid is not None else (user.get("user_refer_number") or 0)
    refer_earning = user.get("user_refer_earning") or 0

    items = [{
        "id": d.get("$id"),
        "name": d.get("user_nickname") or "Friend",
        "paid": d.get("refer_bonus_paid") is True,
        "level": lv,
        "amount": REFER_REWARDS.get(lv, 0),
        "createdAt": d.get("$createdAt") or "",
    } for lv, d in page]

    payload = {
        "items": items, "hasMore": has_more, "level": level,
        "referNumber": refer_number,
        "referEarning": refer_earning,
    }
    if counts is not None:
        payload["counts"] = counts
        payload["signature"] = "|".join(str(x) for x in (
            counts["1"], counts["2"], counts["3"], refer_number, refer_earning))
    ref_cache_put(uid, key, payload, started)
    return jsonify(payload)


# ----------------------------------------------------------------------------
# રેફરલ ઇનામ સર્વર પોતે આપે છે (એડમિન પેનલનું કોઈ કામ નથી)
# ----------------------------------------------------------------------------
def count_completed_offers(email):
    names = set()
    for d in user_tasks(email):
        if classify_task_status(d.get("task_status")) == "completed":
            names.add(norm(d.get("offer_taskname")))
    return len(names)


def upline_chain(friend):
    """મિત્રને રેફર કરનાર (લેવલ ૧), તેને રેફર કરનાર (લેવલ ૨), તેને રેફર કરનાર (લેવલ ૩)"""
    chain, code, seen = [], friend.get("referred_by"), {friend.get("user_refer_code")}
    for level in (1, 2, 3):
        if not code or code in seen:
            break
        seen.add(code)
        up = find_one(C_USERS, "user_refer_code", code)
        if not up or up["$id"] == friend["$id"]:
            break
        chain.append((level, up))
        code = up.get("referred_by")
    return chain


def pay_referral_bonus(friend_id):
    """એક મિત્ર માટે ઉપરના ૩ લેવલને ઇનામ આપે. ફરી ચલાવો તો પણ બે વાર ન જાય."""
    with user_lock(friend_id):
        friend = get_doc(C_USERS, friend_id)
        if friend.get("refer_bonus_paid") is True or not friend.get("referred_by"):
            return False
        if count_completed_offers(friend["user_gmail_account"]) < REFER_TASKS_NEEDED:
            return False

        now = ist_now()
        time_str, stamp = time_date_str(now), int(time.time() * 1000)

        for level, up in upline_chain(friend):
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
                fresh = get_doc(C_USERS, up["$id"])
                balance = float(fresh.get("total_balance_available") or 0)
                earning = float(fresh.get("user_refer_earning") or 0)
                create_doc(C_HISTORY, {
                    "user_gmail_account": fresh["user_gmail_account"],
                    "entry_id": entry_id, "type": "refer_bonus",
                    "title": f"Refer Bonus - Level {level}",
                    "amount": float(reward), "status": "success",
                    "date": time_str, "timestamp": stamp,
                }, doc_id=entry_id)
                try:
                    update_doc(C_USERS, up["$id"], {
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
                forget_user_cache(fresh["user_gmail_account"], "history")
                log.info("રેફર ઇનામ ₹%s આપ્યું: લેવલ %s, %s", reward, level, fresh["user_gmail_account"])

        update_doc(C_USERS, friend_id, {"refer_bonus_paid": True})
    return True


def settle_friends(candidates):
    """ઇનામ બાકી હોય તેવા મિત્રોની યાદીમાંથી, જેમના ૨ અલગ ટાસ્ક મંજૂર છે તેમને જ ઇનામ આપે.
    બધાના ટાસ્ક એક સાથે થોડી માગણીઓમાં વંચાય છે."""
    cand = [f for f in candidates
            if f.get("refer_bonus_paid") is not True and f.get("referred_by") and f.get("user_gmail_account")]
    if not cand:
        return 0
    emails = [f["user_gmail_account"] for f in cand]
    done = defaultdict(set)
    for i in range(0, len(emails), 100):
        for d in list_docs(C_TASKS, [q("equal", "user_gmail_account", emails[i:i + 100])]):
            if classify_task_status(d.get("task_status")) == "completed":
                done[d.get("user_gmail_account")].add(norm(d.get("offer_taskname")))
    paid = 0
    for f in cand:
        if len(done.get(f["user_gmail_account"], ())) < REFER_TASKS_NEEDED:
            continue
        try:
            if pay_referral_bonus(f["$id"]):
                paid += 1
        except Exception as e:  # noqa
            log.warning("રેફર ઇનામ તપાસમાં ભૂલ (%s): %s", f.get("user_gmail_account"), e)
    return paid


def settle_referral_bonuses():
    """ધીમું સલામતી ચક્ર: બંનેમાંથી કોઈની એપ ખુલ્લી ન હોય ત્યારે પણ ઇનામ પહોંચે.
    ફક્ત એવા ખાતા વાંચે જેમને કોઈએ રેફર કર્યા છે અને ઇનામ બાકી છે."""
    try:
        users = list_docs(C_USERS, [q("equal", "refer_bonus_paid", [False]), q("notEqual", "referred_by", [""])])
    except AppwriteError as e:
        log.warning("હળવી શોધ ચાલી નહીં, જૂની રીત વાપરું છું: %s", e)
        users = list_docs(C_USERS, [q("equal", "refer_bonus_paid", [False])])
    return settle_friends(users)


_last_downline_check = {}


def settle_downline(owner_id, friends):
    now = time.time()
    if now - _last_downline_check.get(owner_id, 0) < REFER_ONLINE_CHECK_SECONDS:
        return 0
    _last_downline_check[owner_id] = now
    try:
        return settle_friends(friends)
    except Exception as e:  # noqa
        log.warning("મિત્રોનું રેફર ઇનામ તપાસી શકાયું નહીં: %s", e)
        return 0


def try_pay_own_referral(user, task_docs):
    """મિત્રની પોતાની એપ ટાસ્ક તાજા કરે ત્યારે. શરત પૂરી ન હોય તો કોઈ વધારાનું read નહીં."""
    try:
        if user.get("refer_bonus_paid") is True or not user.get("referred_by"):
            return
        done = {norm(d.get("offer_taskname")) for d in task_docs
                if classify_task_status(d.get("task_status")) == "completed"}
        if len(done) < REFER_TASKS_NEEDED:
            return
        pay_referral_bonus(user["$id"])
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
        resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Allow-Private-Network"] = "true"
    return resp


# ----------------------------------------------------------------------------
# HTML ફાઈલો અને ચિત્રો (public ફોલ્ડરમાંથી)
# ----------------------------------------------------------------------------
APP_PAGES = {"home", "offers", "wallet", "refer", "inviteRefer"}
SAFE_EXT = {".html", ".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico",
            ".ttf", ".woff", ".woff2", ".mp3", ".mp4", ".json", ".txt"}


def not_found_page():
    msg = "Not found"
    if request.remote_addr in ("127.0.0.1", "::1"):
        msg += f"\n\nHTML ફોલ્ડર જ્યાં સર્વર શોધે છે: {PUBLIC_DIR}\nઆ ફોલ્ડરમાં index.html અને loginpage.html હોવી જોઈએ."
    return msg, 404, {"Content-Type": "text/plain; charset=utf-8"}


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve(path):
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


# [નવું] યુઝર કંઈ ન કરે ત્યારે સર્વર જાતે ડેટાબેઝ ન વાંચે એટલે પાછળનું ચક્ર બંધ
os.environ.setdefault("NO_BACKGROUND", "1")
if not os.environ.get("NO_BACKGROUND"):
    start_background()


if __name__ == "__main__":
    log.info("HTML ફોલ્ડર: %s", PUBLIC_DIR)
    if not os.path.isfile(os.path.join(PUBLIC_DIR, "index.html")):
        log.warning("આ ફોલ્ડરમાં index.html મળી નથી! PUBLIC_FOLDER માં સાચું સરનામું લખો.")
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 5000)), threaded=True)
