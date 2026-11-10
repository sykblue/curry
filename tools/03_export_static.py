"""사이트를 고정 파일로 뽑는다 → _site/  (GitHub Pages 용)

    python tools/03_export_static.py            # https://<사용자>.github.io/curry/ 에 올릴 때
    python tools/03_export_static.py /다른이름   # 저장소 이름이 다를 때
    python tools/03_export_static.py ""         # 주소 맨 위(사용자 사이트·자기 도메인)에 올릴 때

Flask 앱을 그대로 불러 화면마다 한 번씩 그려서 저장한다. 레시피 찾기와 오늘의 카레는
서버가 없으므로 브라우저 스크립트(static/recipes.js, index.html 안)가 대신 처리한다.
"""
import json, os, re, shutil, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import app as site                                   # noqa: E402

BASE = (sys.argv[1] if len(sys.argv) > 1 else "/curry").rstrip("/")
OUT = os.path.join(ROOT, "_site")

site.app.config["STATIC_EXPORT"] = True
client = site.app.test_client()
get = lambda path: client.get(path, base_url="http://localhost" + BASE)

# 폴더 주소에는 끝에 / 를 붙인다 (GitHub Pages 는 /recipes 를 /recipes/ 로 한 번 더 돌려보내므로)
HREF = re.compile(r'(href|action)="(' + re.escape(BASE) + r'(?:/[^"?#]*)?)([?#][^"]*)?"')


def fix_links(html):
    def rep(m):
        path, rest = m.group(2), m.group(3) or ""
        last = path.rsplit("/", 1)[-1]
        if "." not in last and not path.endswith("/"):
            path += "/"
        return f'{m.group(1)}="{path}{rest}"'
    return HREF.sub(rep, html)


def write(rel, data):
    dst = os.path.join(OUT, *rel.split("/"))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "wb") as f:
        f.write(data)


def page(url, rel, status=200):
    resp = get(url)
    assert resp.status_code == status, (url, resp.status_code)
    write(rel, fix_links(resp.get_data(as_text=True)).encode("utf-8"))


if os.path.exists(OUT):
    shutil.rmtree(OUT)
os.makedirs(OUT)

page("/", "index.html")
page("/recipes", "recipes/index.html")
page("/ingredients", "ingredients/index.html")
page("/about", "about/index.html")
page("/__404__", "404.html", status=404)
for r in site.RECIPES:
    page(f"/recipe/{r['id']}", f"recipe/{r['id']}/index.html")
for i in site.INGS:
    page(f"/ingredient/{i['key']}", f"ingredient/{i['key']}/index.html")

# JSON API 는 같은 내용의 파일로 둔다
for name in ("recipes", "ingredients", "kg"):
    write(f"api/{name}.json", get(f"/api/{name}").get_data())
os.makedirs(os.path.join(OUT, "data"))
for name in site.DOWNLOADS:
    shutil.copy(os.path.join(site.DATA, name), os.path.join(OUT, "data", name))
shutil.copytree(os.path.join(ROOT, "static"), os.path.join(OUT, "static"))
write(".nojekyll", b"")                              # GitHub Pages 가 파일을 그대로 내보내게 한다

n = sum(len(fs) for _, _, fs in os.walk(OUT))
size = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(OUT) for f in fs)
print(f"{n} files, {size / 1e6:.1f} MB → {OUT}  (base path: '{BASE}')")
