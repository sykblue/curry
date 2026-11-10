"""카레의 작은 방 — 카레 레시피 소개 사이트 (Flask)

데이터는 모두 data/ 의 CSV·JSON 에서 읽는다 (tools/02_build_dataset.py 가 만든다).
    python app.py   →  http://127.0.0.1:5050
"""
import csv, datetime, json, os, random, re, threading, time, urllib.request
from collections import Counter
from flask import Flask, abort, jsonify, redirect, render_template, request, send_from_directory, url_for

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
PAGES = os.path.join(ROOT, "static", "pages")
PER_PAGE = 20

app = Flask(__name__)
app.json.ensure_ascii = False
lock = threading.Lock()
KST = datetime.timezone(datetime.timedelta(hours=9))     # 서버 시간대와 관계없이 한국 시간으로 적는다

LANGS = {"ja": "일본어", "ko": "한국어", "en": "영어", "zh": "중국어", "th": "태국어", "ru": "러시아어", "es": "스페인어", "pt": "포르투갈어"}
CATS = {"method": ("🍳", "만드는 법"), "ingredients": ("🥕", "재료"), "time": ("⏰", "조리 시간"),
        "plating": ("🍽", "담음새"), "etc": ("📎", "그 밖에")}
# 成分識別子 → 표시 이름 (가식부 100g 당)
NUTS = [("ENERC_KCAL", "에너지", "kcal"), ("PROT-", "단백질", "g"), ("FAT-", "지질", "g"), ("CHOCDF-", "탄수화물", "g"),
        ("FIB-", "식이섬유", "g"), ("NACL_EQ", "식염 상당량", "g"), ("K", "칼륨", "mg"), ("CA", "칼슘", "mg"),
        ("FE", "철", "mg"), ("VITC", "비타민 C", "mg"), ("CARTBEQ", "β-카로틴 당량", "μg")]
DOWNLOADS = ["curry_recipes.csv", "curry_recipes.json", "curry_edges.csv", "seibunhyo_edges.csv", "ingredients.json", "curry_kg.ttl"]


SCRIPT = {"ja": re.compile("[ぁ-ヶ一-龥]"), "ko": re.compile("[가-힣]"), "zh": re.compile("[一-龥]"),
          "th": re.compile("[฀-๿]"), "ru": re.compile("[а-яА-Я]")}


# ---------------- 데이터 읽기 ----------------
def load():
    with open(os.path.join(DATA, "curry_recipes.csv"), encoding="utf-8-sig", newline="") as f:
        recipes = list(csv.DictReader(f))
    for r in recipes:
        r["ingredients"] = [k for k in r["ingredients"].split("|") if k]
        r["row_idx"] = int(r["row_idx"])
        r["q"] = r.get("query_ko") or r["query"]        # 화면에 보일 글: 한글 번역이 있으면 번역
        r["a"] = r.get("answer_ko") or r["answer"]
        # 데이터셋에는 문서 언어와 질문 언어가 다른 행(예: 일본어 문서 + 프랑스어 질문)이 섞여 있다
        pat = SCRIPT.get(r["language"])
        r["native"] = bool(pat.search(r["query"])) if pat else True
    order = {l: i for i, l in enumerate(LANGS)}          # 일본어·한국어를 앞에, 언어가 맞는 질문을 앞에
    recipes.sort(key=lambda r: (order.get(r["language"], 99), not r["native"], r["row_idx"]))
    with open(os.path.join(DATA, "ingredients.json"), encoding="utf-8") as f:
        ings = json.load(f)
    with open(os.path.join(DATA, "seibunhyo_edges.csv"), encoding="utf-8-sig", newline="") as f:
        n_nut_edges = sum(1 for _ in f) - 1
    with open(os.path.join(DATA, "curry_edges.csv"), encoding="utf-8-sig", newline="") as f:
        n_rec_edges = sum(1 for _ in f) - 1
    return recipes, ings, {"recipes": len(recipes), "ingredients": len(ings), "rec_edges": n_rec_edges, "nut_edges": n_nut_edges}


RECIPES, INGS, STATS = load()
BY_ID = {r["id"]: r for r in RECIPES}
ING = {i["key"]: i for i in INGS}


def have_images():
    try:
        return set(os.listdir(PAGES))
    except OSError:
        return set()


def read_json(name, default):
    try:
        with open(os.path.join(DATA, name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(name, obj):
    tmp = os.path.join(DATA, name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(DATA, name))


# ---------------- 방명록 · 카운터 저장소 ----------------
# 배포 환경(Render 등)은 서버 파일이 재시작 때 지워지므로 Upstash Redis(REST API)에 저장한다.
# 환경 변수 UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN 이 없으면 이 PC 의 data/*.json 에 저장한다.
REDIS_URL = os.environ.get("UPSTASH_REDIS_REST_URL", "").rstrip("/")
REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")
USE_REDIS = bool(REDIS_URL and REDIS_TOKEN)
COUNTER_START = 1192
BBS_MAX = 200


def redis(*cmd):
    """Upstash REST: 명령을 JSON 배열로 POST 한다. 실패하면 None (사이트는 계속 뜬다)."""
    req = urllib.request.Request(REDIS_URL, data=json.dumps([str(c) for c in cmd]).encode("utf-8"),
                                 headers={"Authorization": "Bearer " + REDIS_TOKEN, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.load(resp).get("result")
    except (OSError, ValueError) as e:
        app.logger.warning("redis %s failed: %s", cmd[0], e)
        return None


def counter(bump=False):
    if USE_REDIS:
        n = redis("INCR", "curry:counter") if bump else redis("GET", "curry:counter")
        return COUNTER_START + int(n or 0)
    with lock:
        c = read_json("counter.json", {"count": COUNTER_START})
        if bump:
            c["count"] += 1
            write_json("counter.json", c)
        return c["count"]


def bbs_posts():
    """최근 글이 앞에 오는 목록."""
    if USE_REDIS:
        out = []
        for raw in redis("LRANGE", "curry:bbs", 0, BBS_MAX - 1) or []:
            try:
                out.append(json.loads(raw))
            except ValueError:
                pass
        return out
    return list(reversed(read_json("bbs.json", [])))


def bbs_add(name, msg):
    post = {"name": name, "message": msg, "date": datetime.datetime.now(KST).strftime("%Y/%m/%d %H:%M")}
    if USE_REDIS:
        post["no"] = int(redis("INCR", "curry:bbs:no") or 0)
        redis("LPUSH", "curry:bbs", json.dumps(post, ensure_ascii=False))
        redis("LTRIM", "curry:bbs", 0, BBS_MAX - 1)
        return
    with lock:
        posts = read_json("bbs.json", [])
        post["no"] = posts[-1]["no"] + 1 if posts else 1
        posts.append(post)
        write_json("bbs.json", posts[-BBS_MAX:])


_last_post = {}


def too_fast(ip):
    """같은 곳에서 30초 안에 또 쓰는 것을 막는다."""
    if USE_REDIS:
        return redis("SET", "curry:bbs:ip:" + ip, 1, "NX", "EX", 30) is None
    now = time.time()
    with lock:
        if now - _last_post.get(ip, 0) < 30:
            return True
        _last_post[ip] = now
        return False


def filtered(args):
    lang, cat, ing, q = args.get("lang", ""), args.get("cat", ""), args.get("ing", ""), args.get("q", "").strip().lower()
    out = RECIPES
    if lang:
        out = [r for r in out if r["language"] == lang]
    if cat:
        out = [r for r in out if r["category"] == cat]
    if ing:
        out = [r for r in out if ing in r["ingredients"]]
    if q:
        out = [r for r in out if q in (r["query"] + " " + r["answer"] + " " + r["q"] + " " + r["a"]).lower()]
    return out


@app.context_processor
def common():
    return {"LANGS": LANGS, "CATS": CATS, "ING": ING, "STATS": STATS, "count": counter(), "imgs": have_images(),
            "today": datetime.datetime.now(KST).date()}


# ---------------- 화면 ----------------
@app.route("/")
def index():
    n = counter(bump=True)
    imgs = have_images()
    pool = [r for r in RECIPES if os.path.basename(r["image"]) in imgs and r["category"] in ("method", "ingredients")
            and r["native"] and r["language"] in ("ja", "ko")] or RECIPES
    pick = random.Random(datetime.datetime.now(KST).date().toordinal()).choice(pool)
    return render_template("index.html", pick=pick, n=n, kiriban=(n % 100 == 0),
                           lang_count=Counter(r["language"] for r in RECIPES),
                           cat_count=Counter(r["category"] for r in RECIPES),
                           top_ings=sorted(INGS, key=lambda i: -i["count"])[:12])


@app.route("/recipes")
def recipes():
    items = filtered(request.args)
    page = max(1, request.args.get("page", 1, type=int))
    pages = max(1, -(-len(items) // PER_PAGE))
    page = min(page, pages)
    args = {k: v for k, v in request.args.items() if k != "page" and v}
    return render_template("recipes.html", items=items[(page - 1) * PER_PAGE: page * PER_PAGE], total=len(items),
                           page=page, pages=pages, args=args, start=(page - 1) * PER_PAGE,
                           ings_sorted=sorted(INGS, key=lambda i: -i["count"]))


@app.route("/recipe/<rid>")
def recipe(rid):
    r = BY_ID.get(rid) or abort(404)
    i = RECIPES.index(r)
    related = [x for x in RECIPES if x is not r and x["language"] == r["language"] and set(x["ingredients"]) & set(r["ingredients"])]
    related.sort(key=lambda x: -len(set(x["ingredients"]) & set(r["ingredients"])))
    return render_template("recipe.html", r=r, prev=RECIPES[i - 1] if i else None,
                           next=RECIPES[i + 1] if i + 1 < len(RECIPES) else None, related=related[:5], NUTS=NUTS[:6])


@app.route("/ingredients")
def ingredients():
    items = sorted(INGS, key=lambda i: -i["count"])
    return render_template("ingredients.html", items=items, top=max(i["count"] for i in items) or 1, downloads=DOWNLOADS)


@app.route("/ingredient/<key>")
def ingredient(key):
    ing = ING.get(key) or abort(404)
    recs = [r for r in RECIPES if key in r["ingredients"]]
    return render_template("ingredient.html", ing=ing, recs=recs, NUTS=NUTS)


@app.route("/bbs", methods=["GET", "POST"])
def bbs():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()[:20] or "이름 없는 카레 애호가"
        msg = (request.form.get("message") or "").strip()[:500]
        ip = (request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0]).strip()
        if request.form.get("homepage"):          # 사람 눈에 안 보이는 칸: 채워져 있으면 자동 프로그램
            return redirect(url_for("bbs"))
        if msg and too_fast(ip):
            return redirect(url_for("bbs", wait=1))
        if msg:
            bbs_add(name, msg)
        return redirect(url_for("bbs"))
    return render_template("bbs.html", posts=bbs_posts(), wait=request.args.get("wait"))


@app.route("/about")
def about():
    return render_template("about.html", downloads=DOWNLOADS)


@app.route("/data/<name>")
def download(name):
    if name not in DOWNLOADS:
        abort(404)
    return send_from_directory(DATA, name, as_attachment=True)


@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


# ---------------- JSON API ----------------
@app.route("/api/recipes")
def api_recipes():
    items = filtered(request.args)
    return jsonify(total=len(items), recipes=items)


@app.route("/api/recipes/<rid>")
def api_recipe(rid):
    return jsonify(BY_ID.get(rid) or abort(404))


@app.route("/api/ingredients")
def api_ingredients():
    return jsonify(INGS)


@app.route("/api/kg")
def api_kg():
    """레시피 -- 식재료 -- 영양소 그래프 (Japanese-FoodKG 와 같은 구조)."""
    nodes = [{"id": r["id"], "type": "Recipe", "label": r["q"]} for r in RECIPES]
    nodes += [{"id": i["key"], "type": "Ingredient", "label": i["name_kg"]} for i in INGS]
    nuts = sorted({n for i in INGS for n in i["nutrition"]})
    nodes += [{"id": n, "type": "Nutrient", "label": n} for n in nuts]
    edges = [{"source": r["id"], "target": k, "type": "hasIngredient"} for r in RECIPES for k in r["ingredients"]]
    edges += [{"source": i["key"], "target": n, "type": "Contains", "value": v} for i in INGS for n, v in i["nutrition"].items()]
    return jsonify(nodes=nodes, edges=edges)


if __name__ == "__main__":
    # 5000 번은 다른 앱이 쓰고 있을 때가 많아 5050 을 기본으로 한다.  예) set PORT=8000
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5050)), debug=False)
