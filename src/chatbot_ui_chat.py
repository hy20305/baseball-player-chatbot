from pathlib import Path
import streamlit as st
import pandas as pd
import requests
import urllib.parse
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import time
from openai import OpenAI
from dotenv import load_dotenv
import os
from bs4 import BeautifulSoup
import streamlit.components.v1 as components
import re

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# === CSV 경로 ===
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
PROFILES_CSV = DATA_DIR / "player_profiles_1.csv"
STATS_CSV = DATA_DIR / "KBO_2025_player_stats_type.csv"
TEAM_INSTA_CSV = DATA_DIR / "team_instagram_1.csv"


profiles = pd.read_csv(PROFILES_CSV, dtype=str)
stats    = pd.read_csv(STATS_CSV, dtype=str)
# stats_2024 = pd.read_csv(STATS_2024_CSV, dtype=str)
# recent_stats = pd.read_csv(RECENT_CSV, dtype=str)
team_instagram = pd.read_csv(TEAM_INSTA_CSV, dtype=str)

# === 유틸 ===
BAD_TOKENS = {"", "-", "None", "none", "nan", "NaN", None}
def clean_str(x): return "" if x in BAD_TOKENS or str(x).strip() in BAD_TOKENS else str(x).strip()
def to_int_safe(x): 
    try: return int(float(str(x).replace(",","")))
    except: return None
def to_float_safe(x): 
    try: return float(str(x).replace(",",""))
    except: return None

def detect_role(row: dict) -> str:
    # 타자 지표 먼저 확인
    if to_float_safe(row.get("AVG")) is not None or to_int_safe(row.get("HR")) is not None:
        return "타자"
    # 투수 지표 확인
    if to_float_safe(row.get("ERA")) is not None or to_float_safe(row.get("WHIP")) is not None:
        return "투수"
    return "선수"

def get_player_realtime_stats(player_id):
    """
    네이버 선수 페이지에서 경기별 기록 (_gameLogArea) 크롤링 (최근 15경기)
    날짜 컬럼 포함 (ul#_gameLogTitleList 의 <a> 태그에서 가져옴)
    """
    url = f"https://m.sports.naver.com/player/index?playerId={player_id}&category=kbo&tab=record"

    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.get(url)
    time.sleep(4)

    soup = BeautifulSoup(driver.page_source, "html.parser")
    driver.quit()

    # 날짜 목록 추출
    date_list = [a.get_text(strip=True) for a in soup.select("#_gameLogTitleList a")]
    if not date_list:
        date_list = ["" for _ in range(15)]

    # 경기별 기록 표
    game_log_div = soup.find("div", id="_gameLogArea")
    if not game_log_div:
        return None, "❌ 최근 경기 기록이 없습니다."

    table = game_log_div.find("table")
    if not table:
        return None, "❌ 최근 경기 기록이 없습니다."

    headers = [th.get_text(strip=True) for th in table.select("thead th")]
    headers.insert(0, "일자")

    rows = []
    for i, tr in enumerate(table.select("tbody tr")[:15]):
        cols = [td.get_text(strip=True) for td in tr.select("td")]
        date_value = date_list[i] if i < len(date_list) else ""
        row = [date_value] + cols
        rows.append(row)

    if not rows:
        return None, "❌ 최근 경기 기록이 없습니다."

    df = pd.DataFrame(rows, columns=headers[:len(rows[0])])
    df = df.fillna("")

    html_table = df.to_html(index=False, classes="styled-table", border=0)

    styled_html = f"""
    <style>
    .styled-table {{
        color: white;
        border-collapse: collapse;
        font-size: 14px;
        width: auto;
        table-layout: auto;
        white-space: nowrap;
    }}
    .styled-table th {{
        background-color: #222;
        color: #4682B4;
        padding: 8px 10px;
        text-align: center;
    }}
    .styled-table td {{
        padding: 6px 10px;
        text-align: center;
        border-bottom: 1px solid #444;
    }}
    .styled-table tr:hover {{
        background-color: #333;
    }}
    </style>
    <div>{html_table}</div>
    """
    return styled_html, None

def get_player_career_stats(player_id):
    """
    네이버 KBO 선수 페이지에서 통산기록(_careerStatsArea) 크롤링
    시즌(연도) 컬럼 포함 + 2025 시즌만 필터링
    """
    url = f"https://m.sports.naver.com/player/index?playerId={player_id}&category=kbo&tab=record"

    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.get(url)
    time.sleep(4)

    try:
        tab_btn = driver.find_element("css selector", '[data-tab="careerStats"]')
        tab_btn.click()
        time.sleep(2)
    except Exception:
        pass

    soup = BeautifulSoup(driver.page_source, "html.parser")
    driver.quit()

    # 시즌 리스트
    season_list = [
        li.get_text(strip=True)
        for li in soup.select("#_careerStatsTitleList li")
        if li.get_text(strip=True)
    ]

    career_div = soup.find("div", id="_careerStatsArea")
    if not career_div:
        return None, "❌ 통산기록 영역을 찾을 수 없습니다."

    table = career_div.find("table")
    if not table:
        return None, "❌ 통산기록 표를 찾을 수 없습니다."

    headers = [th.get_text(strip=True) for th in table.select("thead th")]
    headers.insert(0, "시즌")

    rows = []
    body_rows = table.select("tbody tr")
    for i, tr in enumerate(body_rows):
        cols = [td.get_text(strip=True) for td in tr.select("td")]
        season_value = season_list[i] if i < len(season_list) else ""
        row = [season_value] + cols
        rows.append(row)

    if not rows:
        return None, "❌ 통산기록 데이터가 없습니다."

    df = pd.DataFrame(rows, columns=headers[:len(rows[0])])
    df = df.fillna("")

    # 2025 시즌만 필터링
    df_2025 = df[df["시즌"].astype(str).str.contains("2025", case=False, na=False)]

    if df_2025.empty:
        return None, "❌ 2025 시즌 통산기록을 찾을 수 없습니다."

    html_table = df_2025.to_html(index=False, classes="styled-table", border=0)

    styled_html = f"""
    <style>
    .styled-table {{
        color: white;
        border-collapse: collapse;
        font-size: 14px;
        width: auto;
        table-layout: auto;
        white-space: nowrap;
    }}
    .styled-table th {{
        background-color: #222;
        color: #4682B4;
        padding: 8px 10px;
        text-align: center;
    }}
    .styled-table td {{
        padding: 6px 10px;
        text-align: center;
        border-bottom: 1px solid #444;
    }}
    .styled-table tr:hover {{
        background-color: #333;
    }}
    </style>
    <div>{html_table}</div>
    """
    return styled_html, df_2025

def generate_ai_evaluation(player_name, stats_text):
    """
    선수 이름과 주요 성적을 바탕으로 AI가 자연스럽고 풍부한 평가 문장 생성
    """
    prompt = f"""
    당신은 한국 프로야구 해설위원입니다.
    아래는 {player_name} 선수의 주요 성적 요약입니다.
    이를 바탕으로 2~3문장 정도의 자연스러운 해설 문장을 작성해주세요.

    - 첫 문장은 객관적인 시즌 평가
    - 두 번째 문장은 장점 또는 주목할 점
    - 세 번째 문장은 보완점 또는 향후 기대
    - '~입니다.', '~로 평가됩니다.' 등의 자연스러운 말투

    [성적 요약]
    {stats_text}
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.8,
        max_tokens=200
    )
    return response.choices[0].message.content.strip()

def fetch_news(query, display=3):
    client_id = "pMjEOOg4fs1CEoYxx5cE"
    client_secret = "WUPjhqdWHe"

    enc_query = urllib.parse.quote(query)
    url = f"https://openapi.naver.com/v1/search/news.json?query={enc_query}&display={display}&sort=date"

    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret
    }

    res = requests.get(url, headers=headers)
    if res.status_code != 200:
        return []

    data = res.json().get("items", [])
    news_list = []
    for d in data:
        news_list.append({
            "title": d.get("title", "").replace("<b>", "").replace("</b>", ""),
            "link": d.get("link", "")
        })
    return news_list

def detect_intent_with_ai(user_input):
    """
    OpenAI를 이용해 사용자의 질문 의도를 자동 분류 (성적, 뉴스, 프로필, 기타 등)
    """
    prompt = f"""
    사용자가 아래와 같이 질문했습니다:
    "{user_input}"

    질문의 의도를 아래 중 하나로 정확히 분류하세요:
    - 'news' : 최근 소식, 근황, 인터뷰, 기사, 요즘 어때 등
    - 'profile' : 선수에 대한 기본 정보, 소개, 누구야, 알려줘 등
    - 'stats' : 성적, 기록, 타율, 홈런, 방어율, 삼진 등
    - 'position' : 포지션, 투수, 타자, 외야수, 내야수, 역할 등
    - 'unknown' : 위 4개 중 어디에도 속하지 않으면 unknown

    오직 하나의 단어(news/profile/stats/position/unknown)만 출력하세요.
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=5
    )
    return response.choices[0].message.content.strip().lower()

def generate_answer(user_input):

    recent = pd.read_csv(BASE_DIR / "KBO_10.csv", dtype=str)
    recent["playerId"] = recent["playerId"].ffill()

    # 입력 전처리
    user_input = user_input.strip()
    text = user_input.lower()   # 입력을 소문자로 변환

    # 팀명 + 등번호 → 선수 찾기 기능
    team_number_match = re.search(r"([a-zA-Z가-힣]+)\s*(\d{1,2})번", user_input)
    if team_number_match:
        team_query = team_number_match.group(1).strip()
        number_query = team_number_match.group(2).strip()

        # 팀 이름 매칭
        team_alias = {
            "LG": "LG", "엘지": "LG", "lg": "LG",
            "KT": "KT", "케이티": "KT",
            "SSG": "SSG", "에스에스지": "SSG", "쓱": "SSG",
            "KIA": "KIA", "기아": "KIA",
            "NC": "NC", "엔씨": "NC",
            "롯데": "롯데", "두산": "두산",
            "삼성": "삼성", "한화": "한화",
            "키움": "키움"
        }
        team_std = team_alias.get(team_query, team_query)

        # 팀 + 등번호로 선수 찾기
        match_player = profiles[
            (profiles["team"].str.contains(team_std, na=False)) &
            (profiles["등번호"].astype(str)
             .str.replace("No.", "", case = False)
             .str.strip()
             .replace(".0", "", regex = False)
             == number_query)
        ]

        if not match_player.empty:
            p = match_player.iloc[0].to_dict()
            name = p.get("name")

            df_profile = pd.DataFrame(p.items(), columns=["항목", "내용"])
            df_profile["내용"] = df_profile["내용"].apply(lambda x: "" if str(x) in BAD_TOKENS else x)

            return {
                "role": "bot",
                "content": f"📌 {team_std} {number_query}번은 {name} 선수입니다.",
                "profile": df_profile
            }
        else:
            return {"role": "bot", "content": f" {team_std} {number_query}번 선수 정보를 찾을 수 없습니다."}

    # 팀 이름만 언급된 경우 처리
    team_alias = {
            "LG": "LG", "엘지": "LG", "lg": "LG",
            "KT": "KT", "케이티": "KT",
            "SSG": "SSG", "에스에스지": "SSG", "쓱": "SSG",
            "KIA": "KIA", "기아": "KIA",
            "NC": "NC", "엔씨": "NC",
            "롯데": "롯데", "두산": "두산",
            "삼성": "삼성", "한화": "한화",
            "키움": "키움"
        }
    found_team = None
    user_input_lower = user_input.lower()

    for alias, std in team_alias.items():
        if alias in user_input_lower:
            found_team = std
            break
    
    # 팀 이름 포함 시 처리 (CSV 기반 우선)
    if found_team:
        # 뉴스 / 인스타만 예외로 우선 처리
        if any(word in user_input_lower for word in ["뉴스", "소식", "인스타", "최근 소식", "최근 근황", "소식", "뉴스", "기사", "근황", "최근 이슈", "요즘 어때", "요즘 소식", "인터뷰", "최근 인터뷰", "요즘 근황", "요즘 뭐해"]):
            insta_url = team_instagram.loc[
                team_instagram["team"] == found_team, "instagram"
            ].values[0]
            query = f"{found_team} 야구 KBO 프로야구 경기"
            news_items = fetch_news(query, display=3)
            msg = f"📢 {found_team}의 최근 소식입니다.\n\n📸 구단 인스타그램: [바로가기]({insta_url})\n\n"
            if news_items:
                msg += "📰 야구 관련 뉴스:\n"
                for idx, item in enumerate(news_items, 1):
                    msg += f"[{idx}] [{item['title']}]({item['link']})\n"
            else:
                msg += "📰 관련 뉴스가 없습니다. 대신 구단 인스타그램을 확인해보세요!"
            return {"role": "bot", "content": msg}

        # 그 외의 팀 관련 질문은 CSV 기반 선수 데이터에서 우선 탐색
        team_players = profiles[profiles["team"].str.contains(found_team, na=False)]

        if not team_players.empty:
            prompt = f"""
            사용자가 이렇게 물었습니다:
            "{user_input}"

            아래는 CSV 데이터베이스에서 찾은 '{found_team}' 구단 소속 선수 목록입니다:
            {[name for name in team_players['name'].head(10)]}

            위 선수 데이터를 바탕으로 질문에 맞게 대답하세요.
            - 반드시 CSV에 포함된 선수 중에서만 언급하세요.
            - 은퇴 선수나 CSV 외의 선수는 절대 언급하지 마세요.
            - 문장은 2~3문장으로 자연스럽고 사실적인 톤으로 작성하세요.
            - '~입니다.' 또는 '~하고 있습니다.'로 끝나게 하세요.
            """

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.8,
                max_tokens=250
            )
            ai_answer = response.choices[0].message.content.strip()
            return {"role": "bot", "content": ai_answer}

        # CSV에 해당 팀이 없으면 KBO 전체 맥락으로 처리
        prompt = f"""
        사용자가 이렇게 물었습니다:
        "{user_input}"

        이 질문은 특정 팀({found_team})에 대한 질문입니다.
        하지만 CSV 데이터베이스에서 해당 팀 소속 선수를 찾을 수 없습니다.
        한국 프로야구(KBO)의 최근 흐름과 일반 팀 분위기를 기준으로
        자연스럽고 사실적인 2~3문장으로 답변하세요.
        """
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.8,
            max_tokens=200
        )
        ai_answer = response.choices[0].message.content.strip()
        return {"role": "bot", "content": ai_answer}
    
    # if found_team:
    #     if any(word in user_input_lower for word in ["뉴스", "소식", "인스타", "최근 소식", "최근 근황", "소식", "뉴스", "기사", "근황", "최근 이슈", "요즘 어때", "요즘 소식", "인터뷰", "최근 인터뷰", "요즘 근황"]):
    #         insta_url = team_instagram.loc[
    #             team_instagram["team"] == found_team, "instagram"
    #         ].values[0]

    #         query = f"{found_team} 야구 KBO 프로야구 경기"
    #         news_items = fetch_news(query, display=3)

    #         msg = f"📢 {found_team}의 최근 소식입니다.\n\n"
    #         msg += f"📸 구단 인스타그램: [바로가기]({insta_url})\n\n"

    #         if news_items:
    #             msg += "📰 야구 관련 뉴스:\n"
    #             for idx, item in enumerate(news_items, 1):
    #                 msg += f"[{idx}] [{item['title']}]({item['link']})\n"
    #         else:
    #             msg += "📰 관련 뉴스가 없습니다. 대신 구단 인스타그램을 확인해보세요!"
    #         return {"role": "bot", "content": msg}

    #     # 그 외 문장은 AI로 처리
    #     else:
    #         prompt = f"""
    #         사용자가 이렇게 물었습니다:
    #         "{user_input}"

    #         이 질문은 특정 팀({found_team})과 관련된 주관적 또는 분석형 질문입니다.
    #         당신은 KBO 전문가입니다.
    #         팀의 최근 경기력, 특징, 선수단 분위기 등을 종합해
    #         자연스럽고 사실 기반으로 2~3문장으로 답하세요.
    #         너무 딱딱하지 않게, 정중한 문체로, 문장은 '~입니다'로 끝나게.
    #         """
    #         response = client.chat.completions.create(
    #             model="gpt-4o-mini",
    #             messages=[{"role": "user", "content": prompt}],
    #             temperature=0.9,
    #             max_tokens=180
    #         )
    #         ai_answer = response.choices[0].message.content.strip()
    #         return {"role": "bot", "content": ai_answer}

    # 선수 이름 찾기
    name = None
    user_name = user_input.replace("선수", "").strip()

    # 완전 일치 우선
    exact_matches = [n for n in profiles["name"].dropna().unique() if n == user_name]
    if exact_matches:
        name = exact_matches[0]

    # 이름 전체가 들어간 경우 (공백, 조사 포함)
    if not name:
        for n in profiles["name"].dropna().unique():
            if n in user_input:
                if len(n) >= 2 and user_input.find(n) != -1:
                    name = n
                    break

    # 이름 인식 실패 시 처리
    if not name:
        # 주요 키워드
        typo_keywords = ["성적", "홈런", "타율", "ops", "방어율", "era", "삼진", "이닝", "경기", "요약", "평가"]
        has_stat_word = any(k in text for k in typo_keywords)

        # 팀 이름 목록
        team_names = [t.lower() for t in team_instagram["team"].dropna().unique()]
        found_team = None
        for t in team_names:
            if t in text:
                found_team = t
                break

        # 팀 이름이 포함된 경우 → AI로 넘김 (무조건 오타로 막지 않음)
        if found_team:
            prompt = f"""
            사용자가 이렇게 물었습니다:
            "{user_input}"

            이 질문은 특정 팀({found_team.upper()})과 관련된 분석형 질문입니다.
            당신은 한국 프로야구 전문가이자 해설자입니다.
            팀의 최근 경기력, 주목받는 선수, 분위기, 팬 평가 등을 기반으로
            사실적인 1~2문장으로 자연스럽게 답변하세요.
            너무 딱딱하지 않게, 정중한 문체로, 문장은 '~입니다'로 끝나게.
            """
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.9,
                max_tokens=200
            )
            ai_answer = response.choices[0].message.content.strip()
            return {"role": "bot", "content": ai_answer}

        # 오타 감지
        korean_chars = [ch for ch in user_input if "가" <= ch <= "힣"]
        # 이름이 짧거나 공백, 또는 성적 단어 포함 → 오타로 간주
        if len(korean_chars) <= 2 or any(ch.isspace() for ch in user_input) or has_stat_word:
            return {"role": "bot", "content": "질문을 다시 입력해주세요. (선수 이름을 정확히 입력해주세요)"}

        # 자유형 AI 처리
        prompt = f"""
        사용자가 이렇게 물었습니다:
        "{user_input}"

        특정 선수 이름이나 팀 이름이 명확하지 않은 일반적인 KBO 관련 질문입니다.
        당신은 한국 프로야구 해설자입니다.
        전문가답지만 자연스럽게 1~2문장으로 답변하세요.
        """
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
            max_tokens=200
        )
        ai_answer = response.choices[0].message.content.strip()
        return {"role": "bot", "content": ai_answer}

    intent = detect_intent_with_ai(user_input)

    season = "2025"
    if season == "2025":
        selected_stats = stats

    # 선수 데이터
    p = profiles[profiles["name"] == name].iloc[0].to_dict()
    pid = p.get("playerId")
    stat_rows = selected_stats[selected_stats["playerId"] == pid]

    # 네이버 실시간 최근 경기 기록(10경기까지만)
    if any(k in user_input for k in ["최근 경기", "최근 성적", "최근 기록", "최근 10경기"]):
        result_html, err = get_player_realtime_stats(pid)

        if err:
            return {
                "role": "bot",
                "content": f"❌ {name} 선수의 최근 경기 기록을 불러올 수 없습니다."
            }

        return {
            "role": "bot",
            "content": f"📊 {name} 선수의 최근 경기 기록입니다.",
            "html": result_html
        }
    
    # AI 요약 요청 (성적 요약, 평가 등)
    if any(k in user_input for k in ["성적 요약", "성적 평가", "2025 성적 요약", "올해 성적 평가", "올해 성적 요약"]):
        result_html, df_2025 = get_player_career_stats(pid)

        if df_2025 is None or isinstance(df_2025, str):
            return {"role": "bot", "content": f"❌ {name} 선수의 2025 시즌 성적 데이터를 불러올 수 없습니다."}

        row = df_2025.iloc[0]
        cols = ["타율", "홈런", "타점", "OPS", "ERA", "삼진", "WHIP"]
        stats_text = ", ".join([f"{c}: {row[c]}" for c in cols if c in df_2025.columns and str(row[c]).strip()])

        ai_summary = generate_ai_evaluation(name, stats_text)

        return {
            "role": "bot",
            "content": f"📊 {name} 선수의 2025 시즌 AI 성적 요약입니다.\n\n🎯 {ai_summary}"
        }

    # 네이버 실시간 통산기록 (2025 시즌)
    # "요약"이나 "평가"가 포함된 질문은 제외
    elif any(k in user_input for k in ["2025 성적", "2025 통산기록", "시즌 성적", "올해 성적", "시즌 기록", "성적"]) \
        and not any(k in user_input for k in ["요약", "평가"]):
        try:
            result_html, df_2025 = get_player_career_stats(pid)
        except Exception as e:
            return {"role": "bot", "content": f"❌ 통산기록을 불러오는 중 오류 발생: {e}"}

        if "df_2025" not in locals() or df_2025 is None or isinstance(df_2025, str) or df_2025.empty:
            return {"role": "bot", "content": f"❌ {name} 선수의 2025 통산기록을 불러올 수 없습니다."}

        return {"role": "bot", "content": f"📊 {name} 선수의 2025 시즌 기록입니다.", "html": result_html}
    
    # 최근 소식 기능 (야구 관련 뉴스 + 인스타)
    if any(k in user_input for k in [
        "최근 소식", "소식", "뉴스", "기사", "근황", "최근 이슈", "요즘 어때",
        "요즘 뭐해", "요즘 소식", "최근 근황", "인터뷰", "최근 인터뷰", "요즘 근황",
    ]):
        team = clean_str(p.get("team")) if "p" in locals() else ""
        insta_url = ""
        query = ""

        # 팀 이름만 언급된 경우 처리
        found_team = None
        for t in team_instagram["team"].dropna().unique():
            if t in user_input:
                found_team = t
                break

        # 검색어 구성
        if name:  # 선수 중심 검색
            query = f"{name} 야구선수 KBO 프로야구 경기"
        elif found_team:  # 팀 중심 검색
            query = f"{found_team} 야구 KBO 프로야구 경기"
        else:
            return {"role": "bot", "content": "어느 팀 또는 선수를 말씀하시는지 조금 더 구체적으로 알려주세요."}

        # 인스타그램 링크
        if found_team and found_team in team_instagram["team"].values:
            insta_url = team_instagram.loc[
                team_instagram["team"] == found_team, "instagram"
            ].values[0]
        elif team and team in team_instagram["team"].values:
            insta_url = team_instagram.loc[
                team_instagram["team"] == team, "instagram"
            ].values[0]

        # 뉴스 검색
        news_items = fetch_news(query, display=3)

        if name:
            msg = f"📢 {name} 선수의 최근 소식입니다.\n\n"
        elif found_team:
            msg = f"📢 {found_team}의 최근 소식입니다.\n\n"
        else:
            msg = "📢 최근 소식입니다.\n\n"

        if insta_url:
            msg += f"📸 구단 인스타그램: [바로가기]({insta_url})\n\n"

        if news_items:
            msg += "📰 야구 관련 뉴스:\n"
            for idx, item in enumerate(news_items, 1):
                msg += f"[{idx}] [{item['title']}]({item['link']})\n"
        else:
            msg += "📰 관련 뉴스가 없습니다. 대신 구단 인스타그램을 확인해보세요!"

        return {"role": "bot", "content": msg}
    
    # '포지션'이라고 질문
    if "포지션" in user_input:
        pos = clean_str(p.get("포지션"))
        if pos:
            return {"role": "bot", "content": f"{name} 선수의 포지션은 {pos}입니다."}
        else:
            return {"role": "bot", "content": f"{name} 선수의 포지션 정보는 없습니다."}

    # 포지션 구분/역할 관리 질문 (AI 자유형 문장 생성)
    if any(kw in user_input for kw in [
        "루수", "포수", "외야수", "내야수", "지명타자", "유격수",
        "1루", "2루", "3루", "야수", "투수", "타자",
        "포지션", "역할", "수야", "야?", "뭐하는", "하는 선수", "무슨", "수비"
    ]):
        pos = clean_str(p.get("포지션"))
        team = clean_str(p.get("team"))

        prompt = f"""
        너는 야구 전문가야.
        사용자가 "{user_input}" 라고 물었어.

        아래 정보를 참고해서 자연스럽고 사람처럼 한 문장으로 대답해줘:
        - 선수 이름: {name}
        - 소속 팀: {team}
        - 실제 포지션: {pos if pos else "정보 없음"}

        제약사항:
        - 문장 구조를 고정하지 말고 자유롭게 표현해.(존댓말은 필수)
        - '역할'을 물어보면 '네'나 '아니요'는 앞에 붙이면 안돼. 
        - 질문이 맞으면 '네,' 또는 '맞아요,'로 자연스럽게 시작할 수도 있어.
        - 다르면 '아니요,' 또는 부드럽게 교정하는 문장으로 시작해도 돼.
        - 어색한 형식적 표현 없이 일상적인 말투로 한 문장만 생성해.
        - 사용자가 000 ~야? 이렇게 물어봐도 생성할 때는 선수 이름 뒤에 '선수'를 붙여.
        """

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=1.0, 
            max_tokens=80
        )

        ai_sentence = response.choices[0].message.content.strip()
        return {"role": "bot", "content": ai_sentence}

    # 프로필 특정 항목 요청
    profile_keywords = {
        "생년월일": ["생년월일", "생일"],
        "등번호": ["등번호", "번호"],
        "신장/체중": ["키", "신장", "몸무게", "체중"],
        "team": ["팀", "구단"],
        "포지션": ["포지션"],
        "입단년도": ["입단년도", "데뷔년도"],
        "연봉": ["연봉"], 
        "지명순위": ["지명순위"], 
        "경력": ["경력", "학교", "출신학교"], 
        "입단 계약금": ["입단 계약금", "입단계약금", "계약금"],
    }
    for col, keywords in profile_keywords.items():
        if any(k in user_input for k in keywords):   # 여러 키워드 중 하나라도 포함
            val = clean_str(p.get(col))
            if val:
                return {"role": "bot", "content": f"{name} 선수의 {col}은 {val}입니다."}
            else:
                return {"role": "bot", "content": f"{name} 선수의 {col} 정보는 없습니다."}  
            
    # 특정 지표 자동 인식 (투수/타자 통합 + 역할별 자연응답)
    if any(k in text for k in ["성적", "기록", "타율", "홈런", "평균자책", "ops", "이닝", "세이브", "홀드", "승", "패", "삼진", "출루율", "타점", "득점", "볼넷", "피홈런"]):
        try:
            result_html, df_2025 = get_player_career_stats(pid)
        except Exception as e:
            return {"role": "bot", "content": f"❌ 성적 데이터를 불러오는 중 오류 발생: {e}"}

        if df_2025 is None or isinstance(df_2025, str) or df_2025.empty:
            return {"role": "bot", "content": f"❌ {name} 선수의 2025 시즌 성적 데이터를 불러올 수 없습니다."}

        row = df_2025.iloc[0]
        available_cols = [c.strip() for c in df_2025.columns if c.strip()]

        # 사용자 입력에서 컬럼명 자동 탐색
        found_col = None
        for col in available_cols:
            if col in user_input or col.lower() in user_input.lower():
                found_col = col
                break

        # 컬럼을 못 찾았을 때
        if not found_col:
            role = detect_role(row)
            if role == "타자":
                msg = f"⚾ {name} 선수는 타자이기 때문에 해당 기록은 존재하지 않습니다."
            elif role == "투수":
                msg = f"⚾ {name} 선수는 투수이기 때문에 해당 기록은 존재하지 않습니다."
            else:
                msg = f"⚾ {name} 선수의 해당 지표는 현재 데이터에 없습니다."
            return {"role": "bot", "content": msg}

        val = str(row[found_col]).strip()
        role = detect_role(row)

        # 값이 없거나 '-'인 경우
        if not val or val in ["-", ""]:
            if role == "타자":
                prompt = f"{name} 선수는 타자이기 때문에 '{found_col}' 기록은 제공되지 않습니다. 자연스럽게 한 문장으로 표현해주세요."
            elif role == "투수":
                prompt = f"{name} 선수는 투수이기 때문에 '{found_col}' 기록은 제공되지 않습니다. 자연스럽게 한 문장으로 표현해주세요."
            else:
                prompt = f"{name} 선수의 '{found_col}' 데이터가 현재 제공되지 않습니다. 자연스럽게 한 문장으로 표현해주세요."
        else:
            prompt = f"{name} 선수의 2025 시즌 {found_col}은 {val}입니다. 자연스럽게 한 문장으로 표현해주세요."

        # OpenAI로 문장 생성
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.8,
            max_tokens=100
        )

        ai_sentence = response.choices[0].message.content.strip()
        return {"role": "bot", "content": ai_sentence}
     
    # 프로필 출력 조건 (동명이인 처리 포함)
    profile_triggers = ["선수에 대해 알려줘", "선수 알려줘", "알려줘", "누구야", "정보", "소개"]

    if (
        (len(user_input) <= len(name) + 3 and name in user_input)
        or any(k in user_input for k in profile_triggers)
    ) and not any(k in user_input for k in ["성적", "홈런", "요약", "평가", "뉴스", "근황", "방어율", "통산기록"]):

        # 동명이인 처리
        same_name_players = profiles[profiles["name"] == name]
        if len(same_name_players) > 1:
            options_text = ""
            for idx, (_, row) in enumerate(same_name_players.iterrows(), 1):
                team = row.get("team", "팀 정보 없음")
                number = str(row.get("등번호", "")).replace("No.", "").strip()
                position = row.get("포지션", "포지션 정보 없음")
                options_text += f"{idx}. {team} {number}번 ({position})\n"

            return {
                "role": "bot",
                "content": (
                    f" '{name}' 이름을 가진 선수가 여러 명 있습니다.\n\n"
                    f"아래 중에서 찾으시는 선수를 선택해주세요 👇\n\n{options_text}"
                    f"\n예: '키움 2번 {name}' 처럼 팀명과 등번호를 함께 입력해주세요."
                )
            }

        # 동명이인에 해당 없는 경우 바로 프로필 출력
        p = profiles[profiles["name"] == name].iloc[0].to_dict()
        df_profile = pd.DataFrame(p.items(), columns=["항목", "내용"])
        df_profile["내용"] = df_profile["내용"].apply(lambda x: "" if str(x) in BAD_TOKENS else x)

        return {
            "role": "bot",
            "content": f"📌 {name} 선수의 기본 프로필입니다.",
            "profile": df_profile
        }

    # # 기존의 키워드들에 하나도 해당하지 않으면 AI가 자유롭게 대답
    # if not any(k in text for k in [
    #     "성적", "기록", "타율", "홈런", "평균자책", "ops", "이닝", "세이브", "홀드",
    #     "승", "패", "삼진", "출루율", "타점", "득점", "볼넷", "피홈런",
    #     "뉴스", "근황", "인터뷰", "포지션", "팀", "번호", "등번호", "프로필"
    # ]):
    #     prompt = f"""
    #     사용자가 이렇게 물었습니다:
    #     "{user_input}"

    #     이 질문은 기존의 고정 기능(프로필, 성적, 뉴스, 포지션, 팀/등번호 등)에 해당하지 않습니다.
    #     당신은 한국 프로야구 전문가이자 해설위원입니다.
    #     자연스럽고 정확한 정보 기반으로 1~2문장으로 대답하세요.
    #     너무 포멀하지 않게, 대화체로 친근하지만 지식 있는 어조로 말하세요.
    #     """

    #     response = client.chat.completions.create(
    #         model="gpt-4o-mini",
    #         messages=[{"role": "user", "content": prompt}],
    #         temperature=0.9,
    #         max_tokens=200
    #     )
    #     ai_answer = response.choices[0].message.content.strip()
    #     return {"role": "bot", "content": ai_answer}

    # # 자유형 AI 응답 (프로필 파일 CSV 기반으로 대답)
    # if not any(k in text for k in [
    #     "성적", "기록", "타율", "홈런", "평균자책", "ops", "이닝", "세이브", "홀드",
    #     "승", "패", "삼진", "출루율", "타점", "득점", "볼넷", "피홈런",
    #     "뉴스", "근황", "인터뷰", "포지션", "팀", "번호", "등번호", "프로필"
    # ]):
    #     # 프로필 목록
    #     all_names = set(profiles["name"].dropna().unique())

    #     # 입력문에서 한글 이름 후보 추출
    #     name_pattern = re.findall(r"[가-힣]{2,4}", user_input)
    #     valid_names = [n for n in name_pattern if n in all_names]

    #     # CSV에 있는 선수만 중심으로 AI 대답
    #     if valid_names:
    #         selected_names = ", ".join(valid_names[:3])  # 여러 명 있으면 최대 3명까지만 사용
    #         prompt = f"""
    #         사용자가 이렇게 물었습니다:
    #         "{user_input}"

    #         아래는 실제 KBO 선수 데이터베이스에 존재하는 선수들입니다.
    #         [{selected_names}]

    #         위 선수들 중 질문과 관련이 있는 정보를 중심으로 대답하세요.
    #         - 선수 이름은 실제 DB에 있는 선수만 언급해야 합니다.
    #         - 존재하지 않는 이름은 절대 언급하지 마세요.
    #         - 대답은 2~3문장으로, 자연스럽고 사실적인 어조로 '~입니다.'로 끝내세요.
    #         """

    #         response = client.chat.completions.create(
    #             model="gpt-4o-mini",
    #             messages=[{"role": "user", "content": prompt}],
    #             temperature=0.8,
    #             max_tokens=250
    #         )

    #         ai_answer = response.choices[0].message.content.strip()
    #         return {"role": "bot", "content": ai_answer}

    #     # CSV 내 선수 이름이 없을 때 일반 KBO 기반으로 대답
    #     else:
    #         prompt = f"""
    #         사용자가 이렇게 물었습니다:
    #         "{user_input}"

    #         이 질문에는 데이터베이스에 등록된 선수 이름이 없습니다.
    #         대신, 한국 프로야구(KBO) 전반적인 맥락에서 답변하세요.
    #         - 특정 선수 이름은 언급하지 않습니다.
    #         - 팀, 경기력, 리그 흐름 등을 중심으로 2~3문장으로 대답하세요.
    #         - 문체는 '~입니다.'로 자연스럽게 마무리하세요.
    #         """

    #         response = client.chat.completions.create(
    #             model="gpt-4o-mini",
    #             messages=[{"role": "user", "content": prompt}],
    #             temperature=0.8,
    #             max_tokens=200
    #         )

    #         ai_answer = response.choices[0].message.content.strip()
    #         return {"role": "bot", "content": ai_answer}

    # 자유형 AI 응답 (CSV 기반 우선 + KBO 백업 응답)
    if not any(k in text for k in [
        "성적", "기록", "타율", "홈런", "평균자책", "ops", "이닝", "세이브", "홀드",
        "승", "패", "삼진", "출루율", "타점", "득점", "볼넷", "피홈런",
        "뉴스", "근황", "인터뷰", "포지션", "팀", "번호", "등번호", "프로필"
    ]):
        # 실제 존재하는 선수 이름 목록 (CSV 기반)
        all_names = set(profiles["name"].dropna().unique())

        # 입력문에서 한글 이름 후보 추출
        name_pattern = re.findall(r"[가-힣]{2,4}", user_input)
        valid_names = [n for n in name_pattern if n in all_names]

        if valid_names:
            # CSV에 존재하는 선수만 사용
            name = valid_names[0]
            player_row = profiles[profiles["name"] == name].iloc[0].to_dict()
            team = player_row.get("team", "정보 없음")
            pos = player_row.get("포지션", "정보 없음")

            prompt = f"""
            사용자가 이렇게 물었습니다:
            "{user_input}"

            아래는 실제 CSV 데이터베이스에 존재하는 선수입니다.
            [선수명: {name}, 소속팀: {team}, 포지션: {pos}]

            오직 이 선수의 데이터만 참고해 대답하세요.
            - CSV 파일 외의 선수는 절대 언급하지 않습니다.
            - 은퇴 선수나 과거 선수, 외국인 선수는 언급하지 않습니다.
            - 자연스럽고 사실적인 톤으로 2~3문장 작성하세요.
            - 문장은 '~입니다.' 또는 '~하고 있습니다.'로 끝내세요.
            """

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=250
            )

            ai_answer = response.choices[0].message.content.strip()
            return {"role": "bot", "content": ai_answer}

        else:
            # CSV에 없는 경우 KBO 일반 맥락 기반으로 답변
            prompt = f"""
            사용자가 이렇게 물었습니다:
            "{user_input}"

            질문에 포함된 이름은 현재 CSV 선수 데이터베이스에 없습니다.
            대신 한국 프로야구(KBO) 전체 흐름, 구단 분위기, 경기력 등을 기준으로
            사실적인 범위 안에서 2~3문장으로 답변하세요.
            특정 선수 이름은 언급하지 않습니다.
            자연스럽고 전문가다운 문체로 '~입니다.'로 끝내세요.
            """

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.8,
                max_tokens=250
            )

            ai_answer = response.choices[0].message.content.strip()
            return {"role": "bot", "content": ai_answer}
        
    # 선수만 언급했을 경우
    return {"role": "bot", "content": f"📌 {name} 선수의 기본 프로필입니다.", "profile": df_profile}
    
# === UI ===
st.set_page_config(page_title="⚾ KBO 선수 챗봇", layout="centered")

st.markdown("""
<style>
.stApp { background-color:#000000; }
.block-container { background: rgba(0,0,0,0.85); border-radius: 18px; padding: 20px; }

/* 채팅 말풍선 */
.user-bubble {
  background-color: #d1f0ff; color: #000;
  padding: 10px 15px; border-radius: 15px 15px 0 15px;
  margin: 5px; text-align: right; float: right; clear: both;
  max-width: 80%;
}
.bot-bubble {
  background-color: #fffacd; color: #000;
  padding: 10px 15px; border-radius: 15px 15px 15px 0;
  margin: 5px; text-align: left; float: left; clear: both;
  max-width: 80%;
}
</style>
""", unsafe_allow_html=True)

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# col1, col2 = st.columns([5,8])

# with col1:
#     st.image("chatbot_logo.png", width=500)

# with col2:
#     st.markdown(
#         """
#         <div style="display:flex; align-items:center; height:200px;">
#             <h1 style="margin:0; font-size:3.5em;"><br>KBO 선수 챗봇</h1>
#         </div>
#         <div style="display:flex; align-items:center; height:15px; font-size:1.1em;">
#             🏏 선수의 정보, 성적, 최근 근황을 알려주는 챗봇입니다!
#         </div>
#         """,
#         unsafe_allow_html=True
#     )

# 로고 중앙 정렬
col1, col2, col3 = st.columns([1, 2, 1])

with col2:
    st.image("chatbot_logo_2.png", width=500)

# 채팅 출력
for chat in st.session_state.chat_history:
    if chat["role"] == "user":
        st.markdown(f"<div class='user-bubble'>🧢 {chat['content']}</div>", unsafe_allow_html=True)
    else:
        st.markdown(f"<div class='bot-bubble'>⚾ {chat['content']}</div>", unsafe_allow_html=True)

        if "html" in chat:
            html_code = chat["html"]

            # 표의 행 개수로 높이 계산
            line_count = html_code.count("<tr>")
            dynamic_height = (line_count * 38) + 60   # 기본 상하 여백 포함
            dynamic_height = max(150, min(dynamic_height, 700))

            # 표와 여백 제거 + 스크롤
            components.html(
                f"""
                <div style="
                    margin:0;
                    padding:0;
                    overflow-y:auto;
                    scrollbar-width:thin;
                    height:{dynamic_height}px;
                ">
                    {html_code}
                </div>
                """,
                height=dynamic_height + 10,  # Streamlit 컨테이너 여백 보정
                scrolling=False
            )
        if "profile" in chat:
            profile_df = chat["profile"]

            # CSS 스타일 적용
            st.markdown("""
                <style>
                .styled-profile {
                    border-collapse: collapse;
                    width: 100%;
                    background-color: rgba(20,20,20,0.9);
                    color: white;
                    font-weight: 400; 
                    border-radius: 10px;
                }
                .styled-profile th {
                    background-color: #222;
                    color: #4682B4;
                    font-weight: 600;
                    text-align: center;
                    padding: 8px;
                    border-bottom: 2px solid #555;
                }
                .styled-profile td {
                    text-align: center;
                    padding: 6px;
                    border-bottom: 1px solid #444;
                }
                .styled-profile tr:hover {
                    background-color: #333;
                }
                </style>
            """, unsafe_allow_html=True)

            # DataFrame
            html_table = profile_df.to_html(index=False, classes="styled-profile", border=0)
            st.markdown(html_table, unsafe_allow_html=True)     

        if "stats" in chat:
            st.dataframe(chat["stats"], use_container_width=True)

# 입력창
user_input = st.chat_input(placeholder= "예: 양의지 선수에 대해 알려줘, 구본혁 2025년 성적 요약")
if user_input:
    st.session_state.chat_history.append({"role": "user", "content": user_input})
    bot_msg = generate_answer(user_input)
    st.session_state.chat_history.append(bot_msg)

    st.rerun()
