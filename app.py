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
              or item.select_one(".prdPrice")
              or item.select_one("b")
          )
          link_el = item.select_one("a")
          if title_el and price_el:
            p_name = title_el.text.strip()
            price_match = re.search(r"[\d,]+", price_el.text)
            if price_match:
              p_price = float(price_match.group(0).replace(",", ""))
              spec = parse_specification("", p_name)
              if spec["unit"] == target_unit:
                unit_price = (
                    round(p_price / spec["total_volume"], 2)
                    if spec["total_volume"] > 0
                    else p_price
                )
                href = (
                    link_el["href"] if (link_el and link_el.get("href")) else ""
                )
                item_url = (
                    href
                    if href.startswith("http")
                    else f"https://m.momoshop.com.tw/{href.lstrip('/')}"
                )
                results.append({
                    "title": p_name,
                    "price": p_price,
                    "unit_price": unit_price,
                    "url": item_url,
                })
  except Exception:
    pass
  return min(results, key=lambda x: x["unit_price"]) if results else None


def search_pchome(keyword, target_unit):
  url = f"https://ecshweb.pchome.com.tw/search/v3.3/all/results?q={urllib.parse.quote(keyword)}&page=1&sort=rnk/dc"
  results = []
  try:
    res = requests.get(url, headers=PC_HEADERS, timeout=6)
    if res.status_code == 200:
      data = res.json()
      for p in data.get("prods", [])[:5]:
        p_name = p.get("name", "")
        p_price = float(p.get("price", 0))
        spec = parse_specification("", p_name)
        if spec["unit"] == target_unit:
          unit_price = (
              round(p_price / spec["total_volume"], 2)
              if spec["total_volume"] > 0
              else p_price
          )
          p_id = p.get("Id", "")
          results.append({
              "title": p_name,
              "price": p_price,
              "unit_price": unit_price,
              "url": f"https://24h.pchome.com.tw/prod/{p_id}",
          })
  except Exception:
    pass
  return min(results, key=lambda x: x["unit_price"]) if results else None


def search_yahoo(keyword, target_unit):
  url = f"https://tw.buy.yahoo.com/search/product?p={urllib.parse.quote(keyword)}"
  results = []
  try:
    res = requests.get(url, headers=PC_HEADERS, timeout=6)
    if res.status_code == 200:
      soup = BeautifulSoup(res.text, "html.parser")
      items = (
          soup.select("li[data-item-id]")
          or soup.select("div.BaseGridItem__grid___2wuGy")
          or soup.select(".sc-bwzfXH")
      )
      for item in items[:5]:
        title_el = (
            item.select_one(".BaseGridItem__title___2HWui")
            or item.select_one("span[class*='title']")
            or item.find("span")
        )
        price_el = (
            item.select_one(".BaseGridItem__price___31jkj")
            or item.select_one("em")
        )
        link_el = item.find("a")
        if title_el and price_el:
          p_name = title_el.text.strip()
          price_match = re.search(r"[\d,]+", price_el.text)
          if price_match:
            p_price = float(price_match.group(0).replace(",", ""))
            spec = parse_specification("", p_name)
            if spec["unit"] == target_unit:
              unit_price = (
                  round(p_price / spec["total_volume"], 2)
                  if spec["total_volume"] > 0
                  else p_price
              )
              item_url = (
                  link_el["href"] if (link_el and "href" in link_el.attrs) else ""
              )
              results.append({
                  "title": p_name,
                  "price": p_price,
                  "unit_price": unit_price,
                  "url": item_url,
              })
  except Exception:
    pass
  return min(results, key=lambda x: x["unit_price"]) if results else None


uploaded_file = st.file_uploader(
    "請上傳 Excel 活動排程清單 (.xlsx)", type=["xlsx"]
)

if uploaded_file is not None:
  try:
    xl = pd.ExcelFile(uploaded_file)
    sheet_names = xl.sheet_names
    st.success(f"檔案解析成功！共有 {len(sheet_names)} 個工作表")
  except Exception as e:
    st.error(f"檔案讀取失敗：{e}")
    sheet_names = []

  if sheet_names:
    default_sheets = [s for s in sheet_names if "支" in s or "sheet" in s]
    selected_sheets = st.multiselect(
        "請勾選欲進行比價的工作表：",
        options=sheet_names,
        default=default_sheets if default_sheets else [sheet_names[0]],
    )

    if st.button("🚀 開始自動跨平台比價（momo / PChome / Yahoo）", type="primary"):
      all_results = []
      progress_bar = st.progress(0)
      status_text = st.empty()

      items_to_process = []
      for sname in selected_sheets:
        try:
          df = pd.read_excel(uploaded_file, sheet_name=sname)
          if "品名" not in df.columns:
            continue
          df_valid = df.dropna(subset=["品名"])
          for _, row in df_valid.iterrows():
            pname = str(row.get("品名", "")).strip()
            price = row.get("東森價", 0)
            main_item = (
                str(row.get("主商品(含型號)", ""))
                if pd.notna(row.get("主商品(含型號)"))
                else ""
            )
            if pname and pd.notna(price) and float(price) > 0:
              items_to_process.append({
                  "sheet": sname,
                  "品名": pname,
                  "主商品": main_item,
                  "東森價": float(price),
              })
        except Exception:
          pass

      total_count = len(items_to_process)
      if total_count == 0:
        st.warning("所選工作表中未找到有效的品名與價格！")
      else:
        for idx, item in enumerate(items_to_process):
          status_text.text(
              f"正在比價 ({idx+1}/{total_count}): 【{item['品名']}】..."
          )

          spec = parse_specification(item["主商品"], item["品名"])
          vol = spec["total_volume"]
          unit = spec["unit"]
          unit_price = (
              round(item["東森價"] / vol, 2) if vol > 0 else item["東森價"]
          )

          kw = extract_core_keywords(item["品名"])

          best_momo = search_momo(kw, unit)
          best_pchome = search_pchome(kw, unit)
          best_yahoo = search_yahoo(kw, unit)

          valid_comps = []
          if best_momo:
            valid_comps.append(("momo", best_momo["unit_price"]))
          if best_pchome:
            valid_comps.append(("PChome", best_pchome["unit_price"]))
          if best_yahoo:
            valid_comps.append(("Yahoo", best_yahoo["unit_price"]))

          lowest_platform = "-"
          lowest_unit_price = None
          advantage = "-"

          if valid_comps:
            valid_comps.sort(key=lambda x: x[1])
            lowest_platform = valid_comps[0][0]
            lowest_unit_price = valid_comps[0][1]

            diff = (
                (lowest_unit_price - unit_price) / lowest_unit_price
            ) * 100
            if diff > 0:
              advantage = f"比最優競業便宜 {round(diff, 1)}%"
            else:
              advantage = f"比最優競業貴 {round(abs(diff), 1)}%"

          all_results.append({
              "來源工作表": item["sheet"],
              "本台品名": item["品名"],
              "主商品規格": item["主商品"],
              "本台售價": item["東森價"],
              "換算總量": f"{vol} {unit}",
              "本台換算單價": f"{unit_price} 元/{unit}",
              "momo品名": best_momo["title"] if best_momo else "查無同單位",
              "momo售價": best_momo["price"] if best_momo else "-",
              "momo換算單價": (
                  f"{best_momo['unit_price']} 元/{unit}"
                  if best_momo
                  else "-"
              ),
              "momo參考連結": best_momo["url"] if best_momo else "-",
              "PChome品名": (
                  best_pchome["title"] if best_pchome else "查無同單位"
              ),
              "PChome售價": best_pchome["price"] if best_pchome else "-",
              "PChome換算單價": (
                  f"{best_pchome['unit_price']} 元/{unit}"
                  if best_pchome
                  else "-"
              ),
              "PChome參考連結": (
                  best_pchome["url"] if best_pchome else "-"
              ),
              "Yahoo品名": (
                  best_yahoo["title"] if best_yahoo else "查無同單位"
              ),
              "Yahoo售價": best_yahoo["price"] if best_yahoo else "-",
              "Yahoo換算單價": (
                  f"{best_yahoo['unit_price']} 元/{unit}"
                  if best_yahoo
                  else "-"
              ),
              "Yahoo參考連結": best_yahoo["url"] if best_yahoo else "-",
              "競業最低平台": lowest_platform,
              "競業最低換算單價": (
                  f"{lowest_unit_price} 元/{unit}"
                  if lowest_unit_price
                  else "-"
              ),
              "我方價差優勢": advantage,
          })

          progress_bar.progress((idx + 1) / total_count)
          time.sleep(1.2)

        status_text.text("比價完成！")
        result_df = pd.DataFrame(all_results)
        st.dataframe(result_df)

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
          result_df.to_excel(writer, index=False, sheet_name="三大電商比價結果")
        output.seek(0)

        st.download_button(
            label="📥 下載三大電商比價分析報表 (.xlsx)",
            data=output,
            file_name="雙11三大電商單入比價分析表.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
