import os
import time
import requests
import re
import feedparser
from collections import Counter
from beem import Hive
from beem.account import Account

# --- AYARLAR ---
HIVE_NODE = "https://api.hive.blog"
USERNAME = os.getenv("HIVE_USERNAME")
POSTING_KEY = os.getenv("HIVE_POSTING_KEY")
REPO_NAME = os.getenv("REPO_NAME", "hive-bot")

MAIN_TAG = "crypto"
TAGS = ["crypto", "hive", "bitcoin", "data", "news"]

COVER_IMAGE_URL = f"https://raw.githubusercontent.com/{USERNAME}/{REPO_NAME}/main/cover.png"

def get_global_prices():
    try:
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {"ids": "bitcoin,ethereum,solana,hive", "vs_currencies": "usd", "include_24hr_change": "true"}
        return requests.get(url, params=params, timeout=10).json()
    except Exception as e:
        print(f"Global fiyat hatası: {e}")
        return None

def get_hive_engine_data():
    try:
        url = "https://api.hive-engine.com/rpc/contracts"
        payload = {
            "jsonrpc": "2.0", "id": 1, "method": "find",
            "params": {
                "contract": "market", "table": "metrics", "query": {},
                "limit": 100, "indexes": ["volume", "desc"]
            }
        }
        response = requests.post(url, json=payload, timeout=10).json()
        data = response.get("result", [])
        valid_data = [d for d in data if float(d.get("volume", 0)) > 0]
        
        top_10_volume = valid_data[:10]
        top_5_price = sorted(valid_data, key=lambda x: float(x.get("price", 0)), reverse=True)[:5]
        return top_10_volume, top_5_price
    except Exception as e:
        print(f"Hive Engine veri hatası: {e}")
        return [], []

def get_trending_tags():
    try:
        hive = Hive(node=HIVE_NODE)
        discussions = hive.get_discussions_by_trending({"limit": 20})
        tag_counter = Counter()
        for post in discussions:
            tags = post.get("tags", []) or post.get("json_metadata", {}).get("tags", [])
            for tag in tags:
                if tag and tag != MAIN_TAG:
                    tag_counter[tag.lower()] += 1
        return [tag for tag, count in tag_counter.most_common(5)]
    except Exception as e:
        return ["crypto", "hive", "art", "gaming", "finance"]

def get_crypto_news():
    try:
        feed = feedparser.parse("https://www.coindesk.com/arc/outboundfeeds/rss/")
        news_items = []
        for entry in feed.entries[:5]:
            title = entry.title
            link = entry.link
            summary = entry.get('summary', entry.get('description', ''))
            clean_summary = re.sub(r'<[^>]+>', '', summary)[:120].strip() + "..."
            news_items.append(f"**[{title}]({link})**\n> {clean_summary}\n")
        return news_items
    except Exception as e:
        print(f"Haber çekme hatası: {e}")
        return ["*News feed temporarily unavailable.*"]

def generate_post(global_prices, he_volume, he_price, trending_tags, news):
    today = time.strftime("%B %d, %Y")
    
    global_md = "| Asset | Price (USD) | 24h Change |\n| :--- | :--- | :--- |\n"
    for coin_id, name in [("bitcoin", "Bitcoin (BTC)"), ("ethereum", "Ethereum (ETH)"), ("solana", "Solana (SOL)"), ("hive", "Hive (HIVE)")]:
        if coin_id in global_prices:
            p = global_prices[coin_id]
            emoji = "🟢" if p['usd_24h_change'] >= 0 else "🔴"
            global_md += f"| **{name}** | ${p['usd']:,.4f} | {emoji} {p['usd_24h_change']:.2f}% |\n"

    he_vol_md = "| Rank | Token | Volume (24h) |\n| :--- | :--- | :--- |\n"
    for i, token in enumerate(he_volume, 1):
        he_vol_md += f"| {i} | **{token['symbol']}** | ${float(token['volume']):,.2f} |\n"

    he_price_md = "| Rank | Token | Price (HIVE) |\n| :--- | :--- | :--- |\n"
    for i, token in enumerate(he_price, 1):
        he_price_md += f"| {i} | **{token['symbol']}** | {float(token['price']):,.4f} |\n"

    tags_md = ", ".join([f"`#{tag}`" for tag in trending_tags])
    news_md = "\n".join([f"{i+1}. {item}" for i, item in enumerate(news)])

    # Yapay zeka kalıplarından (uzun tire, oxford virgülü) arındırılmış doğal metin
    content = f"""![Daily Market Pulse]({COVER_IMAGE_URL})

# Daily Market Pulse: Crypto, Hive Engine & Top News | {today}

Hello Hive Community! 👋

Welcome to your daily data brief. No fluff and no opinions, just the raw numbers from the global crypto markets, the Hive Engine ecosystem and the top news of the day.

---

###  1. Global Market Overview

{global_md}

---

### 🐝 2. Hive Engine Top 10 (By 24h Volume)

{he_vol_md}

---

###  3. Hive Engine Top 5 (Highest Priced)

{he_price_md}

---

### 🔥 4. Trending Topics on Hive

{tags_md}

---

### 📰 5. Top 5 Crypto News of the Day

{news_md}

---

*Note: This report brings together real-time data from public sources like CoinGecko, Hive Engine and CoinDesk. The information is meant for educational purposes and is not financial advice. Please do your own research.*

What are your thoughts on today's market and news? Let's discuss below! 👇

#crypto #hive #bitcoin #data #news
"""
    return f"Daily Market Pulse: Crypto, Hive Engine & Top News | {today}", content

def publish_post(title, body):
    try:
        hive = Hive(node=HIVE_NODE, keys=[POSTING_KEY], nobroadcast=False)
        account = Account(USERNAME, blockchain_instance=hive)
        permlink = f"daily-market-pulse-{time.strftime('%Y-%m-%d')}"
        
        print("📡 Publishing to Hive...")
        tx = account.comment(
            title=title, body=body, permlink=permlink,
            parent_author="", parent_permlink=MAIN_TAG, tags=TAGS
        )
        print(f"✅ SUCCESSFULLY PUBLISHED!")
        print(f"🔗 Link: https://hive.blog/{MAIN_TAG}/@{USERNAME}/{permlink}")
    except Exception as e:
        print(f"❌ Publishing Error: {e}")

def main():
    print("=" * 50)
    print("🐝 Hive Daily Market Pulse Bot Starting...")
    print("=" * 50)
    
    if not USERNAME or not POSTING_KEY:
        print("❌ ERROR: Secrets missing!")
        return
    
    print("📡 Fetching Global Prices...")
    prices = get_global_prices()
    if not prices:
        print("❌ Global prices failed. Aborting.")
        return
    
    print(" Fetching Hive Engine Data...")
    he_vol, he_price = get_hive_engine_data()
    
    print("📡 Fetching Trending Tags...")
    tags = get_trending_tags()
    
    print("📡 Fetching Crypto News...")
    news = get_crypto_news()
    
    title, body = generate_post(prices, he_vol, he_price, tags, news)
    publish_post(title, body)

if __name__ == "__main__":
    main()
