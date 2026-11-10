"""카레 관련 행의 레시피 페이지 이미지를 Hugging Face datasets-server 에서 내려받는다.
(parquet 전체 11GB 를 받지 않기 위해 /rows API 를 행 단위로, 천천히 호출)"""
import csv, json, os, re, sys, time
import requests
from PIL import Image
from io import BytesIO

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
csv.field_size_limit(10**9)
PAT = re.compile(r"カレー|かれー|카레|커리|curry|curri|咖喱|咖哩|cà ri|แกง|กะหรี่|карри|كاري|caril|masala|マサラ|キーマ|kari", re.I)
API = "https://datasets-server.huggingface.co/rows"
DS = dict(dataset="racineai/VDR_Cooking_Recipes", config="filtered", split="train")

rows = list(csv.DictReader(open(os.path.join(ROOT, "data/raw/all_text.csv"), encoding="utf-8")))
for i, r in enumerate(rows):          # 파일 순서 = 데이터셋 전체 행 순서
    r["row_idx"] = i
curry = [r for r in rows if PAT.search(r["query"] + " " + r["answer"])]
json.dump([{k: r[k] for k in ("row_idx", "id", "query", "answer", "language")} for r in curry],
          open(os.path.join(ROOT, "data/raw/curry_rows.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("curry rows:", len(curry), flush=True)

out = os.path.join(ROOT, "static/pages")
s = requests.Session()
fail = 0
for n, r in enumerate(curry):
    dst = os.path.join(out, f"{r['row_idx']:05d}.jpg")
    if os.path.exists(dst):
        continue
    for attempt in range(8):
        try:
            resp = s.get(API, params=dict(DS, offset=r["row_idx"], length=1), timeout=60)
            if resp.status_code == 429:
                time.sleep(60); continue
            row = resp.json()["rows"][0]["row"]
            assert row["id"] == r["id"], "id mismatch"
            img = s.get(row["image"]["src"], timeout=120)
            img.raise_for_status()
            im = Image.open(BytesIO(img.content)).convert("RGB")
            im.thumbnail((1100, 1600))
            im.save(dst, "JPEG", quality=80)
            tn = im.copy(); tn.thumbnail((240, 320))
            tn.save(os.path.join(out, f"{r['row_idx']:05d}_s.jpg"), "JPEG", quality=72)
            break
        except AssertionError as e:
            print("MISMATCH", r["row_idx"], flush=True); break
        except Exception as e:
            time.sleep(5 * (attempt + 1))
    else:
        fail += 1; print("FAIL", r["row_idx"], flush=True)
    if n % 20 == 0:
        print(n, "/", len(curry), flush=True)
    time.sleep(1.2)
print("done, fail =", fail, flush=True)
