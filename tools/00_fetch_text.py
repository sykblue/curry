"""racineai/VDR_Cooking_Recipes (filtered) 의 글 열만 내려받는다 → data/raw/all_text.csv

from datasets import load_dataset
ds = load_dataset("racineai/VDR_Cooking_Recipes", "filtered")
와 같은 데이터이지만, 사진까지 받으면 약 11GB 이므로 DuckDB 로 parquet 의 필요한 열만 읽는다.
"""
import os
import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
out = os.path.join(ROOT, "data", "raw", "all_text.csv").replace("\\", "/")
os.makedirs(os.path.dirname(out), exist_ok=True)
files = [f"https://huggingface.co/datasets/racineai/VDR_Cooking_Recipes/resolve/main/filtered-0000{i}-of-00006.parquet" for i in range(6)]

con = duckdb.connect()
con.sql("INSTALL httpfs; LOAD httpfs;")
con.sql(f"""copy (select id, query, answer, language, filename, file_row_number
                  from read_parquet({files}, filename=true, file_row_number=true))
            to '{out}' (header, delimiter ',')""")
print(con.sql(f"select language, count(*) from '{out}' group by 1 order by 2 desc").fetchall())
