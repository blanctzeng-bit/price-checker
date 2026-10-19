import io
import re
import time
import urllib.parse
from bs4 import BeautifulSoup
import pandas as pd
import requests
import streamlit as st

st.set_page_config(
    page_title="全網電商智能比價工具", page_icon="🛒", layout="wide"
)

st.title("🛒 電商商品智能比價工具（Google 購物全網聚合版）")
st.markdown(
    "透過 Google Shopping 聚合引擎，自動比對 **momo、Yahoo 購物、PChome、酷澎**"
    " 等全網即時單入售價！"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
        " like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
}


def parse_specification(text):
  """精準解析規格與組裝入數：支援 30ml超值5入組、20ml超值6入、600ml任選6入、100ml*4"""
  vol_match = re.search(
      r"(\d+(?:\.\d+)?)\s*(ml|g|公克|錠|包|片|盒|入)", text, re.IGNORECASE
  )
  unit_size = float(vol_match.group(1)) if vol_match else 1.0
  unit = vol_match.group(2).lower() if vol_match else "入"
  if unit == "公克":
    unit = "g"

  count_match = re.search(
      r"(?:[\*xX×]|超值|任選|共)?\s*(\d+)\s*(?:入組|入|盒|瓶|支|罐|包)", text
  )
  count = 1
  if count_match:
    count = int(count_match.group(1))
  else:
    star = re.search(r"[\*xX×]\s*(\d+)", text)
    if star:
      count = int(star.group(1))

  return {
      "unit_size": unit_size,
      "unit": unit,
      "count": count,
      "total_volume": unit_size * count,
  }


def clean_search_keyword(name):
  """清洗出最強搜尋詞：去掉入數後綴與味道列舉"""
  name = re.sub(r"[-－—].*$", "", name)
  name = re.sub(
      r"\d+(?:\.\d+)?\s*(?:ml|g|公克|錠|包|片|盒|入)?\s*(?:[\*xX×]|超值|任選|共)?\s*\d+\s*(?:入組|入|盒|瓶|支|罐|包)?",
      "",
      name,
  )
  name = re.sub(r"\d+(?:\.\d+)?\s*(?:ml|g|公克|錠|包|片|盒|入)", "", name)
  name = re.sub(
      r"(雙11|爆殺組|回饋組|熱燃強化組|黃金三效|特惠組|專案|搶購組|主商品：?|【.*?】|\[.*?\]|超值組|超值|任選|組)",
      "",
      name,
  )
  return name.strip()


def search_google_shopping(keyword, target_unit):
  """直連 Google 購物比價，一次抓取 momo、PChome、Yahoo、酷澎等各大通路"""
  encoded = urllib.parse.quote(keyword)
  url = f"https://www.google.com/search?q={encoded}&tbm=shop&hl=zh-TW&gl=tw"
  results = {"momo": None, "PChome": None, "Yahoo": None, "其他最優": None}

  try:
    res = requests.get(url, headers=HEADERS, timeout=8)
    if res.status_code == 200:
      soup = BeautifulSoup(res.text, "html.parser")

      # 解析 Google 購物的商品卡片
      items = soup.select(".sh-dgr__content") or soup.select(".sh-dlr__content")
      for it in items:
        title_el = it.select_one("h3") or it.select_one(".tAxDx")
        price_el = it.select_one(".a8Pemb") or it.select_one(".OFFNJ")
        merchant_el = (
            it.select_one(".aULzUe")
            or it.select_one(".IuHnof")
            or it.select_one(".E5ocAb")
        )
        link_el = it.select_one("a")

        if title_el and price_el and merchant_el:
          t_text = title_el.text.strip()
          m_text = merchant_el.text.strip()
          p_match = re.search(r"[\d,]+", price_el.text)
          if not p_match:
            continue
          price = float(p_match.group(0).replace(",", ""))

          # 解析該競品的規格與單價
          c_spec = parse_specification(t_text)
          if c_spec["unit"] == target_unit and c_spec["total_volume"] > 0:
            unit_p = round(price / c_spec["total_volume"], 2)
            p_data = {
                "title": t_text,
                "price": price,
                "unit_price": unit_p,
                "url": (
                    f"https://www.google.com{link_el['href']}"
                    if link_el and link_el.get("href")
                    else ""
                ),
            }

            # 依電商平台分類
            if "momo" in m_text or "富邦" in m_text:
              if not results["momo"] or unit_p < results["momo"]["unit_price"]:
                results["momo"] = p_data
            elif "PChome" in m_text or "24h" in m_text:
              if (
                  not results["PChome"]
                  or unit_p < results["PChome"]["unit_price"]
              ):
                results["PChome"] = p_data
            elif "Yahoo" in m_text or "雅虎" in m_text:
              if (
                  not results["Yahoo"]
                  or unit_p < results["Yahoo"]["unit_price"]
              ):
                results["Yahoo"] = p_data
            else:
              if (
                  not results["其他最優"]
                  or unit_p < results["其他最優"]["unit_price"]
              ):
                results["其他最優"] = {**p_data, "platform": m_text}
  except Exception:
    pass

  return results


# -----------------------------
# 頁面主體邏輯
# -----------------------------

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

    if st.button("🚀 開始全網電商智能比價", type="primary"):
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

          # 1. 精準規格換算
          full_str = f"{item['品名']} {item['主商品']}"
          spec = parse_specification(full_str)
          vol = spec["total_volume"]
          unit = spec["unit"]
          unit_price = (
              round(item["東森價"] / vol, 2) if vol > 0 else item["東森價"]
          )

          # 2. 透過 Google 購物聚合比價
          kw = clean_search_keyword(item["品名"])
          comps = search_google_shopping(kw, unit)

          # 3. 找出全網最優競價
          valid_list = []
          for p_name in ["momo", "PChome", "Yahoo"]:
            if comps[p_name]:
              valid_list.append((p_name, comps[p_name]["unit_price"]))
          if comps["其他最優"]:
            valid_list.append(
                (comps["其他最優"]["platform"], comps["其他最優"]["unit_price"])
            )

          lowest_platform = "-"
          lowest_unit_price = None
          advantage = "-"

          if valid_list:
            valid_list.sort(key=lambda x: x[1])
            lowest_platform = valid_list[0][0]
            lowest_unit_price = valid_list[0][1]

            diff = (
                (lowest_unit_price - unit_price) / lowest_unit_price
            ) * 100
            if diff > 0:
              advantage = f"比競業便宜 {round(diff, 1)}%"
            else:
              advantage = f"比競業貴 {round(abs(diff), 1)}%"

          all_results.append({
              "來源工作表": item["sheet"],
              "本台品名": item["品名"],
              "換算總量": f"{vol} {unit} ({spec['unit_size']}{unit} x {spec['count']}入)",
              "本台售價": item["東森價"],
              "本台換算單價": f"{unit_price} 元/{unit}",
              # momo
              "momo品名": (
                  comps["momo"]["title"] if comps["momo"] else "查無同單位"
              ),
              "momo售價": comps["momo"]["price"] if comps["momo"] else "-",
              "momo換算單價": (
                  f"{comps['momo']['unit_price']} 元/{unit}"
                  if comps["momo"]
                  else "-"
              ),
              # Yahoo
              "Yahoo品名": (
                  comps["Yahoo"]["title"] if comps["Yahoo"] else "查無同單位"
              ),
              "Yahoo售價": (
                  comps["Yahoo"]["price"] if comps["Yahoo"] else "-"
              ),
              "Yahoo換算單價": (
                  f"{comps['Yahoo']['unit_price']} 元/{unit}"
                  if comps["Yahoo"]
                  else "-"
              ),
              # PChome
              "PChome品名": (
                  comps["PChome"]["title"] if comps["PChome"] else "查無同單位"
              ),
              "PChome售價": (
                  comps["PChome"]["price"] if comps["PChome"] else "-"
              ),
              "PChome換算單價": (
                  f"{comps['PChome']['unit_price']} 元/{unit}"
                  if comps["PChome"]
                  else "-"
              ),
              # 總評
              "全網最低平台": lowest_platform,
              "全網最低單價": (
                  f"{lowest_unit_price} 元/{unit}"
                  if lowest_unit_price
                  else "-"
              ),
              "我方價差優勢": advantage,
          })

          progress_bar.progress((idx + 1) / total_count)
          time.sleep(1.5)

        status_text.text("比價完成！")
        result_df = pd.DataFrame(all_results)
        st.dataframe(result_df)

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
          result_df.to_excel(
              writer, index=False, sheet_name="全網電商比價結果"
          )
        output.seek(0)

        st.download_button(
            label="📥 下載全網電商比價分析報表 (.xlsx)",
            data=output,
            file_name="全網電商單入比價分析表.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
