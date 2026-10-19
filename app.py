import io
import json
import re
import time
import urllib.parse
from bs4 import BeautifulSoup
import pandas as pd
import requests
import streamlit as st

st.set_page_config(
    page_title="多平台競業單入比價工具", page_icon="🛒", layout="wide"
)

st.title("🛒 電商商品批次跨平台比價工具（momo / PChome / Yahoo）")
st.markdown(
    "支援大促活動報表（含多入拆解、小樣換算每 ml/單入單價），同時比對 **momo、PChome、Yahoo"
    " 購物中心**！"
)

MOMO_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X)"
        " AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148"
        " Safari/604.1"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://m.momoshop.com.tw/",
    "Connection": "keep-alive",
}

PC_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
        " like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


def parse_specification(main_item_str, product_name):
  text = f"{product_name} {main_item_str or ''}"
  multi_pack = re.search(
      r"(\d+(?:\.\d+)?)\s*(ml|g|公克|錠|包|片|盒|入)[\*xX×](\d+)", text
  )
  if multi_pack:
    unit_size = float(multi_pack.group(1))
    unit = multi_pack.group(2)
    count = int(multi_pack.group(3))
    return {
        "unit_size": unit_size,
        "unit": unit,
        "count": count,
        "total_volume": unit_size * count,
    }

  single_pack = re.search(r"(\d+(?:\.\d+)?)\s*(ml|g|公克|錠|包|片|盒|入)", text)
  if single_pack:
    unit_size = float(single_pack.group(1))
    unit = single_pack.group(2)
    return {
        "unit_size": unit_size,
        "unit": unit,
        "count": 1,
        "total_volume": unit_size,
    }

  count_only = re.search(r"[\*xX×](\d+)|(\d+)\s*入", text)
  if count_only:
    count = int(count_only.group(1) or count_only.group(2))
    return {"unit_size": 1, "unit": "入", "count": count, "total_volume": count}

  return {"unit_size": 1, "unit": "入", "count": 1, "total_volume": 1}


def extract_core_keywords(product_name):
  clean = re.sub(
      r"(雙11|爆殺組|回饋組|熱燃強化組|黃金三效|特惠組|專案|搶購組|主商品：?|【.*?】|\[.*?\])",
      "",
      product_name,
  )
  return clean.strip()


def search_momo(keyword, target_unit):
  encoded_kw = urllib.parse.quote(keyword)
  url = f"https://m.momoshop.com.tw/search.momo?searchKeyword={encoded_kw}&_advFirst=N&_advCp=N&curPage=1&searchType=1"
  results = []
  session = requests.Session()
  try:
    res = session.get(url, headers=MOMO_HEADERS, timeout=8)
    if res.status_code == 200:
      match_json = re.search(
          r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
          res.text,
      )
      if match_json:
        try:
          data = json.loads(match_json.group(1))
          prods = (
              data.get("props", {})
              .get("pageProps", {})
              .get("goodsInfo", {})
              .get("goodsList", [])
          )
          for p in prods[:6]:
            p_name = p.get("goodsName", "")
            p_price = float(p.get("salePrice") or p.get("price", 0))
            if p_name and p_price > 0:
              spec = parse_specification("", p_name)
              if spec["unit"] == target_unit:
                unit_price = (
                    round(p_price / spec["total_volume"], 2)
                    if spec["total_volume"] > 0
                    else p_price
                )
                g_code = p.get("goodsCode", "")
                results.append({
                    "title": p_name,
                    "price": p_price,
                    "unit_price": unit_price,
                    "url": (
                        f"https://m.momoshop.com.tw/goods.momo?i_code={g_code}"
                    ),
                })
        except Exception:
          pass

      if not results:
        soup = BeautifulSoup(res.text, "html.parser")
        items = (
            soup.select("li.goodsItemLi")
            or soup.select(".prdList li")
            or soup.select("article.prdItem")
        )
        for item in items[:6]:
          title_el = (
              item.select_one(".prdName")
              or item.select_one(".goodsName")
              or item.select_one("h3")
          )
          price_el = (
              item.select_one(".price")
              or
