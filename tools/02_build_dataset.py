"""카레 데이터셋(CSV / JSON)과 Japanese-FoodKG 형식의 지식 그래프를 만든다.

입력
  data/raw/curry_rows.json       racineai/VDR_Cooking_Recipes (filtered) 에서 뽑은 카레 관련 행
  data/raw/seibun/honpyo.xlsx    日本食品標準成分表 本表 (文部科学省)
  data/ingredient_dict.json      식재료 사전 (다국어 별칭 + 成分表 食品番号)
  data/translations_ko.json      일본어 문서 46건의 질문·답 한글 번역

출력 (모두 data/)
  curry_recipes.csv / .json      사이트가 읽는 레시피 Q&A 데이터
  curry_edges.csv                레시피 -- 식재료 엣지   (FoodKG 의 cookpad_edges.csv 와 같은 열)
  seibunhyo_edges.csv            식재료 -- 영양소 엣지   (FoodKG 의 seibunhyo_edges.csv 와 같은 열)
  ingredients.json               식재료별 영양 성분 + 등장 레시피
  curry_kg.ttl                   FoodKG 의 create_kg.py 와 같은 네임스페이스의 Turtle

Japanese-FoodKG 의 preprocessing_data.py / create_kg.py 는 Cookpad·楽天 원본 DB 와 pandas 가
있어야 돌아가므로 그대로 실행하지 않고, 같은 규칙(カタカナ→ひらがな 정규화, 食品名 분류,
엣지 CSV 열 구성, RDF 네임스페이스)을 표준 라이브러리로 옮겨 적용했다.
"""
import csv, json, os, re, uuid
from collections import Counter, defaultdict
from urllib.parse import quote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = lambda *p: os.path.join(ROOT, "data", *p)
SOURCE = "VDR_Cooking_Recipes"


# ---------- Japanese-FoodKG 규칙 ----------
def kata2hira(s):
    """jaconv.kata2hira 와 같은 동작 (ァ-ヶ → ぁ-ゖ). FoodKG 의 식재료 정규화."""
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in s)


def clean_and_classify(name):
    """FoodKG preprocessing_data.py 의 clean_and_classify 와 같은 食品名 분해."""
    sub = re.search(r"＜(.*?)＞", name); row = re.sub(r"＜(.*?)＞", "", name)
    typ = re.search(r"（(.*?)）", row);  row = re.sub(r"（(.*?)）", "", row)
    mid = re.search(r"［(.*?)］", row);  row = re.sub(r"［(.*?)］", "", row)
    return {"sub_category": sub.group(1) if sub else "", "type_category": typ.group(1) if typ else "",
            "mid_category": mid.group(1) if mid else "", "small_category": row.strip().replace("\u3000", " ")}


# ---------- 1. 成分表 ----------
def load_seibunhyo():
    cache = D("raw", "seibun", "honpyo.json")
    if not os.path.exists(cache):
        import openpyxl
        ws = openpyxl.load_workbook(D("raw", "seibun", "honpyo.xlsx"), read_only=True, data_only=True)["表全体"]
        rows = [r for i, r in enumerate(ws.iter_rows(values_only=True)) if i >= 11]   # header_row=11 (FoodKG 와 동일)
        json.dump({"hdr": [str(h).strip() if h else "" for h in rows[0]],
                   "foods": [[str(c) if c is not None else "" for c in r] for r in rows[1:] if r[1]]},
                  open(cache, "w", encoding="utf-8"), ensure_ascii=False)
    j = json.load(open(cache, encoding="utf-8"))
    hdr = j["hdr"]
    foods = {}
    for f in j["foods"]:
        vals = {}
        for h, v in zip(hdr[4:], f[4:]):
            if not h:
                continue
            v = v.strip().strip("()（）")
            try:
                vals[h] = float(v)
            except ValueError:
                pass                      # Tr, -, * 등은 FoodKG 처럼 엣지를 만들지 않는다
        foods[f[1]] = {"food_name": f[3].replace("\u3000", " "), "values": vals}
    return foods


# ---------- 2. 식재료 매칭 ----------
LATIN = re.compile(r"^[\x00-\x7fÀ-ɏЀ-ӿ ]+$")


def build_matchers(ings):
    out = []
    for ing in ings:
        pats = []
        for a in dict.fromkeys(ing["alias"]):
            a_l = a.lower()
            if LATIN.match(a_l):          # 알파벳·키릴: 단어 앞 경계에서만
                pats.append(r"(?<![a-zà-ɏа-я])" + re.escape(a_l.strip()) + (r"(?![a-zà-ɏа-я])" if a_l.endswith(" ") or len(a_l.strip()) <= 3 else ""))
            else:
                pats.append(re.escape(a_l))
        out.append((ing["key"], re.compile("|".join(pats))))
    return out


# 한 글자 한자 별칭이 다른 낱말 안에서 걸리는 것을 막는다
BLOCK = {
    "abura": re.compile(r"醤油|醬油|酱油|しょうゆ|蠔油|蚝油|奶油|黃油|黄油|牛油|油揚げ|сливочн\w* масл\w*|น้ำมันหอย"),
    "tamago": re.compile(r"蛋白質|蛋白质|蛋糕|eggplant"),
    "butaniku": re.compile(r"豚骨"),
    "pan": re.compile(r"パン粉|フライパン|빵가루|ジャパン|パンチ|パンプキン|サンパン|パンチェッタ"),
    "negi": re.compile(r"たまねぎ|玉ねぎ|洋葱|洋蔥"),
    "kosho": re.compile(r"болгарск\w* перец|перец чили|сладк\w* перец"),
    "gyunyu": re.compile(r"ココナッツミルク|코코넛 ?밀크|coconut milk|lait de coco|leche de coco|leite de coco|кокосов\w* молок\w*|soy ?milk|buttermilk|นมถั่วเหลือง|ขนม|соев\w* молок\w*|lait de soja|leche de soja|leite de soja"),
    "lemon": re.compile(r"lemon ?grass|レモングラス|레몬 ?그라스|citronnelle"),
    "pasta": re.compile(r"pasta de \w+|curry paste|томатн\w* паст\w*|карри паст\w*|паст\w* карри"),
    "gohan": re.compile(r"ข้าวโพด|米粉|rice vinegar|rice wine|rice flour"),
    "togarashi": re.compile(r"พริกไทย|พริกหวาน|pimenta-do-reino|pimenta do reino|pimenta preta"),
    "sato": re.compile(r"糖アルコール"),
    "toriniku": re.compile(r"雞蛋|鸡蛋|雞湯|鸡汤|ไข่ไก่|chicken stock|chicken broth"),
}


def find_ingredients(text, matchers):
    low = text.lower()
    found = []
    for key, pat in matchers:
        t = low
        if key in BLOCK:
            t = BLOCK[key].sub(" ", t)
        if pat.search(t):
            found.append(key)
    return found


# ---------- 3. 질문 분류 ----------
CATS = [
    ("time", "조리 시간", "⏰", r"時間|何分|시간|몇 분|how long|cooking time|minutes|多久|多長|多长|เวลา|นานแค่ไหน|сколько времени|время приготовлен|tiempo|quanto tempo|combien de temps"),
    ("plating", "담음새", "🍽", r"盛り付け|画像|見た目|写真|플레이팅|담겨|담아|이미지|모습|시각|visual|presentation|image|plating|plated|擺盤|摆盘|圖片|图片|外觀|外观|จัดจาน|ในภาพ|ภาพ|подач|изображен|выгляд|presentación|imagen|apresentação|imagem|présentation"),
    ("ingredients", "재료", "🥕", r"材料|食材|재료|ingredient|ส่วนผสม|วัตถุดิบ|ингредиент|ingrédient|配料|用料"),
    ("method", "만드는 법", "🍳", r"作り方|調理方法|調理法|方法|手順|作る|만드는|만들|조리|방법|과정|how to|how do|how is|prepare|preparation|steps|process|如何|怎麼|怎么|怎样|步驟|步骤|做法|製作|制作|วิธี|ขั้นตอน|как приготов|как готов|приготовлен|cómo|como preparar|como fazer|comment|wie "),
]


def classify(q):
    ql = q.lower()
    for key, _, _, pat in CATS:
        if re.search(pat, ql):
            return key
    return "etc"


# ---------- main ----------
def main():
    rows = json.load(open(D("raw", "curry_rows.json"), encoding="utf-8"))
    ings = json.load(open(D("ingredient_dict.json"), encoding="utf-8"))
    ing_by_key = {i["key"]: i for i in ings}
    foods = load_seibunhyo()
    matchers = build_matchers(ings)

    lang_fix = {"kr": "ko"}
    tr = json.load(open(D("translations_ko.json"), encoding="utf-8"))   # 손으로 옮긴 한글 번역 (일본어 문서 46건)
    recipes, edges = [], []
    for r in rows:
        rid = f"c{r['row_idx']:05d}"
        text = r["query"] + "\n" + r["answer"]
        found = find_ingredients(text, matchers)
        rec = {
            "id": rid, "row_idx": r["row_idx"], "hf_id": r["id"],
            "language": lang_fix.get(r["language"], r["language"]),
            "category": classify(r["query"]),
            "query": r["query"].strip(), "answer": r["answer"].strip(),
            "query_ko": tr.get(rid, {}).get("q", ""), "answer_ko": tr.get(rid, {}).get("a", ""),
            "ingredients": found,
            "image": f"pages/{r['row_idx']:05d}.jpg", "thumb": f"pages/{r['row_idx']:05d}_s.jpg",
            "source": SOURCE,
        }
        recipes.append(rec)
        for k in found:   # FoodKG: recipe_id, recipe_title, ingredient_name, edge_type, data_source
            edges.append([rid, kata2hira(rec["query"]), kata2hira(ing_by_key[k]["ja"]), "recipe-ingredient", SOURCE])

    # 레시피 CSV / JSON
    cols = ["id", "row_idx", "hf_id", "language", "category", "query", "answer", "query_ko", "answer_ko", "ingredients", "image", "thumb", "source"]
    with open(D("curry_recipes.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f); w.writerow(cols)
        for rec in recipes:
            w.writerow([("|".join(rec[c]) if c == "ingredients" else rec[c]) for c in cols])
    json.dump(recipes, open(D("curry_recipes.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    with open(D("curry_edges.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f); w.writerow(["recipe_id", "recipe_title", "ingredient_name", "edge_type", "data_source"]); w.writerows(edges)

    # 식재료 -- 영양소 엣지
    used = Counter(k for rec in recipes for k in rec["ingredients"])
    co = defaultdict(Counter)
    for rec in recipes:
        for a in rec["ingredients"]:
            for b in rec["ingredients"]:
                if a != b:
                    co[a][b] += 1
    seibun_edges, ing_out = [], []
    for ing in ings:
        food = foods[ing["code"]]
        name_h = kata2hira(food["food_name"])
        for nut, val in food["values"].items():
            seibun_edges.append([ing["code"], name_h, nut, val, "ingredient-nutrition", "seibunhyo"])
        ing_out.append({
            "key": ing["key"], "ja": ing["ja"], "ko": ing["ko"], "emoji": ing["emoji"],
            "name_kg": kata2hira(ing["ja"]),
            "food_code": ing["code"], "food_name": food["food_name"], **clean_and_classify(food["food_name"].replace(" ", "\u3000")),
            "nutrition": food["values"], "count": used[ing["key"]],
            "pairs": [k for k, _ in co[ing["key"]].most_common(6)],
        })
    with open(D("seibunhyo_edges.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f); w.writerow(["food_code", "food_name", "nutrition_name", "value", "edge_type", "data_source"]); w.writerows(seibun_edges)
    json.dump(ing_out, open(D("ingredients.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # Turtle (create_kg.py 와 같은 네임스페이스 / 술어)
    NS = uuid.UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")
    esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "")
    L = ["@prefix recipe: <http://JapaneseFoodKG.org/Recipe/> .", "@prefix ingredient: <http://JapaneseFoodKG.org/Ingredient/> .",
         "@prefix nutrition: <http://JapaneseFoodKG.org/Nutrition/> .", "@prefix ds: <http://JapaneseFoodKG.org/data_source/> .",
         "@prefix relation: <http://JapaneseFoodKG.org/relation/> .", "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .", ""]
    iu = {i["key"]: uuid.uuid5(NS, "ingredient/" + i["name_kg"]) for i in ing_out}
    for rec in recipes:
        s = f"recipe:{quote(rec['id'], safe='')}"
        L.append(f'{s} a recipe:Recipe ; recipe:title "{esc(kata2hira(rec["query"]))}" ; ds:source "{SOURCE}"'
                 + "".join(f" ;\n    recipe:hasIngredient ingredient:{iu[k]}" for k in rec["ingredients"]) + " .")
    nuts = sorted({n for i in ing_out for n in i["nutrition"]})
    nu = {n: uuid.uuid5(NS, "nutrition/" + n) for n in nuts}
    for n in nuts:
        L.append(f'nutrition:{nu[n]} a nutrition:Nutrient ; nutrition:name "{esc(n)}" .')
    for i in ing_out:
        L.append(f'ingredient:{iu[i["key"]]} a ingredient:Ingredient ; ingredient:name "{esc(i["name_kg"])}" .')
        for n, v in i["nutrition"].items():
            rel = uuid.uuid5(NS, f"rel/{i['key']}/{n}")
            L.append(f'ingredient:{iu[i["key"]]} relation:{rel} nutrition:{nu[n]} .')
            L.append(f'relation:{rel} a relation:Contains ; relation:value "{v}"^^xsd:float ; ds:source "seibunhyo" .')
    open(D("curry_kg.ttl"), "w", encoding="utf-8").write("\n".join(L) + "\n")

    print("recipes:", len(recipes), "| recipe-ingredient edges:", len(edges), "| ingredient-nutrition edges:", len(seibun_edges))
    print("languages:", dict(Counter(r["language"] for r in recipes)))
    print("categories:", dict(Counter(r["category"] for r in recipes)))
    print("no ingredient:", sum(1 for r in recipes if not r["ingredients"]))
    print("top:", [(ing_by_key[k]["ko"], n) for k, n in used.most_common(50)])
    for i in ing_out:
        print(" ", i["key"], i["food_code"], i["food_name"])


if __name__ == "__main__":
    main()
