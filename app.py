import io
import re
import time
import urllib.parse
from bs4 import BeautifulSoup
import openpyxl
import pandas as pd
import requests
import streamlit as st

st.set_page_config(
    page_title="電商競業單入比價工具", page_icon="🛒", layout="wide"
)

st.title("🛒 電商商品批次競業單入比價工具")
st.markdown(
    "支援大促活動報表（含多入拆解、小樣換算每 ml/單入單價），一鍵自動比價並產出分析報表。"
)

HEADERS = {
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


def search_pchome(keyword):
  url = f"https://ecshweb.pchome.com.tw/search/v3.3/all/results?q={urllib.parse.quote(keyword)}&page=1&sort=rnk/dc"
  results = []
  try:
    res = requests.get(url, headers=HEADERS, timeout=6)
    if res.status_code == 200:
      data = res.json()
      prods = data.get("prods", [])
      for p in prods[:4]:
        p_name = p.get("name", "")
        p_price = float(p.get("price", 0))
        spec = parse_specification("", p_name)
        unit_price = (
            round(p_price / spec["total_volume"], 2)
            if spec["total_volume"] > 0
            else p_price
        )
        results.append({
            "platform": "PChome",
            "title": p_name,
            "price": p_price,
            "unit_price": unit_price,
            "unit": spec["unit"],
            "url": f"https://24h.pchome.com.tw/prod/{p.get('Id')}",
        })
  except Exception:
    pass
  return results


def search_momo(keyword):
  url = f"https://m.momoshop.com.tw/search.momo?searchKeyword={urllib.parse.quote(keyword)}"
  results = []
  try:
    res = requests.get(url, headers=HEADERS, timeout=6)
    if res.status_code == 200:
      soup = BeautifulSoup(res.text, "html.parser")
      items = soup.select("li.goodsItemLi") or soup.select(".prdList li")
      for item in items[:4]:
        title_el = item.select_one(".prdName") or item.select_one(".goodsName")
        price_el = item.select_one(".price") or item.select_one(".prdPrice")
        link_el = item.select_one("a")
        if title_el and price_el:
          p_name = title_el.text.strip()
          price_match = re.search(r"[\d,]+", price_el.text)
          if price_match:
            p_price = float(price_match.group(0).replace(",", ""))
            spec = parse_specification("", p_name)
            unit_price = (
                round(p_price / spec["total_volume"], 2)
                if spec["total_volume"] > 0
                else p_price
            )
            item_url = (
                f"https://m.momoshop.com.tw/{link_el['href']}"
                if link_el and link_el.get("href")
                else ""
            )
            results.append({
                "platform": "momo",
                "title": p_name,
                "price": p_price,
                "unit_price": unit_price,
                "unit": spec["unit"],
                "url": item_url,
            })
  except Exception:
    pass
  return results


uploaded_file = st.file_uploader(
    "請上傳 Excel 活動排程清單 (.xlsx)", type=["xlsx"]
)

if uploaded_file is not None:
  wb = openpyxl.load_workbook(uploaded_file, data_only=True)
  sheet_names = wb.sheetnames

  st.success(f"檔案上傳成功！偵測到工作表：{', '.join(sheet_names)}")

  default_sheets = [s for s in sheet_names if "支" in s or "sheet" in s]
  selected_sheets = st.multiselect(
      "請勾選欲進行比價的工作表：",
      options=sheet_names,
      default=default_sheets if default_sheets else [sheet_names[0]],
  )

  if st.button("🚀 開始自動比價換算", type="primary"):
    all_results = []
    progress_bar = st.progress(0)
    status_text = st.empty()

    items_to_process = []
    for sname in selected_sheets:
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
        unit_price = round(item["東森價"] / vol, 2) if vol > 0 else item["東森價"]

        kw = extract_core_keywords(item["品名"])
        comp_candidates = []
        comp_candidates.extend(search_pchome(kw))
        comp_candidates.extend(search_momo(kw))

        matched = [c for c in comp_candidates if c["unit"] == unit]
        lowest = (
            min(matched, key=lambda x: x["unit_price"]) if matched else None
        )

        advantage = "-"
        if lowest and lowest["unit_price"] > 0:
          diff = (
              (lowest["unit_price"] - unit_price) / lowest["unit_price"]
          ) * 100
          advantage = (
              f"比競業便宜 {round(diff, 1)}%"
              if diff > 0
              else f"比競業貴 {round(abs(diff), 1)}%"
          )

        all_results.append({
            "來源工作表": item["sheet"],
            "本台品名": item["品名"],
            "主商品規格": item["主商品"],
            "本台售價": item["東森價"],
            "換算總量": f"{vol} {unit}",
            "本台換算單價": f"{unit_price} 元/{unit}",
            "競業最優平台": lowest["platform"] if lowest else "查無同單位商品",
            "競業品名": lowest["title"] if lowest else "-",
            "競業售價": lowest["price"] if lowest else "-",
            "競業換算單價": (
                f"{lowest['unit_price']} 元/{unit}" if lowest else "-"
            ),
            "價差優勢": advantage,
            "競品參考連結": lowest["url"] if lowest else "-",
        })

        progress_bar.progress((idx + 1) / total_count)
        time.sleep(1)

      status_text.text("比價完成！")
      result_df = pd.DataFrame(all_results)
      st.dataframe(result_df)

      output = io.BytesIO()
      with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        result_df.to_excel(writer, index=False, sheet_name="競業比價結果")
      output.seek(0)

      st.download_button(
          label="📥 下載比價結果分析報表 (.xlsx)",
          data=output,
          file_name="雙11商品競業單入比價分析表.xlsx",
          mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      )
