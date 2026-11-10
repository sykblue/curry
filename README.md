# 카레의 작은 방

카레 레시피 소개 사이트입니다. Flask 서버가 `data/` 의 CSV·JSON 을 읽어 보여 주고, 화면은 2000년대 초 일본 개인 홈페이지 분위기로 꾸몄습니다.

## 실행

```
pip install -r requirements.txt
python app.py
```

브라우저에서 http://127.0.0.1:5050 을 엽니다. 포트를 바꾸려면 `set PORT=8000` 뒤에 실행합니다.

## 화면

| 주소 | 내용 |
|---|---|
| `/` | 처음 화면 — 오늘의 카레, 분류별 건수 |
| `/recipes` | 레시피 수첩 — 언어·궁금한 것·재료·낱말로 찾기 |
| `/recipe/<id>` | 질문과 답, 원본 레시피 문서 사진, 재료 영양표 |
| `/ingredients`, `/ingredient/<key>` | 식재료 도감 — 식재료별 영양 성분과 나오는 레시피 |
| `/about` | 자료 출처, 데이터 내려받기 |
| `/api/recipes`, `/api/recipes/<id>`, `/api/ingredients`, `/api/kg` | JSON API |

## 데이터

| 파일 | 내용 |
|---|---|
| `data/curry_recipes.csv` / `.json` | 카레 레시피 Q&A 265건 (사이트가 읽는 것은 CSV) |
| `data/curry_edges.csv` | 레시피 ─ 식재료 엣지. 열 구성은 Japanese-FoodKG 의 `cookpad_edges.csv` 와 같음 |
| `data/seibunhyo_edges.csv` | 식재료 ─ 영양소 엣지. Japanese-FoodKG 의 `seibunhyo_edges.csv` 와 같음 |
| `data/ingredients.json` | 식재료 49종의 영양 성분, 등장 횟수, 함께 나오는 재료 |
| `data/curry_kg.ttl` | Japanese-FoodKG 의 `create_kg.py` 와 같은 이름공간으로 쓴 Turtle |
| `data/translations_ko.json` | 일본어 문서 46건의 질문·답 한글 번역 (CSV 의 `query_ko`, `answer_ko` 열로 들어감) |
| `data/ingredient_dict.json` | 손으로 만든 식재료 사전 (다국어 별칭, 成分表 食品番号) |
| `static/pages/` | 레시피 문서 사진 (큰 것 + `_s` 썸네일) |

### 출처

- **racineai/VDR_Cooking_Recipes** (`filtered`, Apache-2.0) — 11,171행 가운데 질문·답에 카레가 나오는 265행.
- **Japanese-FoodKG** — 「레시피 ─ 식재료 ─ 영양소」 그래프 구조, 가타카나→히라가나 정규화, 食品名 분류, 엣지 CSV 형식, RDF 이름공간을 따랐습니다. 저장소에는 코드만 있고 원본 레시피 데이터(Cookpad·라쿠텐, 계약 필요)는 없어서, 레시피 쪽은 위 데이터셋으로 대신했습니다. 저장소의 스크립트는 MySQL·pandas 가 필요해 그대로 돌리지 않고 같은 규칙을 `tools/02_build_dataset.py` 에 옮겼습니다.
- **日本食品標準成分表** (文部科学省, 2026-03-27 갱신판) — 식재료 영양 성분.

### 데이터 다시 만들기

```
pip install -r tools/requirements.txt
python tools/00_fetch_text.py      # 데이터셋의 글 열만 받기 → data/raw/all_text.csv
python tools/01_fetch_images.py    # 카레 행 고르기 + 문서 사진 받기 (중단해도 이어서 받음)
python tools/02_build_dataset.py   # CSV · JSON · TTL 만들기
```

`datasets.load_dataset(...)` 을 쓰지 않은 이유: `filtered` 는 사진이 들어 있어 약 11GB 이고, 이 PC 에서는 pyarrow·pandas 의 DLL 이 애플리케이션 제어 정책에 막혀 있습니다. 그래서 DuckDB 로 parquet 의 글 열만 읽고, 사진은 Hugging Face datasets-server 에서 필요한 행만 받았습니다.

## 배포 (GitHub Pages)

GitHub Pages 는 고정 파일만 보여 주므로, 사이트를 파일로 뽑아 `gh-pages` 브랜치에 올립니다.

```
python tools/03_export_static.py        # _site/ 에 고정 파일 생성 (주소가 /curry/ 일 때)
cd _site
git init -b gh-pages
git add -A
git commit -m "사이트 갱신"
git push -f https://github.com/sykblue/curry.git gh-pages
```

고정 사이트에서는 레시피 찾기와 "오늘의 카레"를 브라우저 스크립트가 처리합니다 (`static/recipes.js`).
JSON API 는 `api/recipes.json`, `api/ingredients.json`, `api/kg.json` 파일로 대신합니다.
저장소 이름을 바꾸면 `python tools/03_export_static.py /새이름` 으로 다시 뽑아야 링크가 맞습니다.

## 알아 둘 점

- 재료는 질문·답 글에서 낱말을 찾아 붙인 것이라, 빠지거나 잘못 붙은 것이 있습니다.
- 영양 성분은 재료 100g당 값이며 요리 1인분의 영양가가 아닙니다.
- 데이터셋의 `language` 는 문서의 언어라서 질문 글의 언어와 다른 행이 있습니다 (예: 일본어 문서에 프랑스어 질문). 목록에서는 뒤쪽에 둡니다.
- `python app.py` 는 내 PC 에서 볼 때 쓰는 개발용 서버입니다. 공개 사이트는 위의 고정 파일입니다.
