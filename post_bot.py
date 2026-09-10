print("🚀 DEBUG: SCRIPT BASARIYLA BASLADI!")

import os
import time
import json
import requests
import re
import feedparser
from collections import Counter
from beem import Hive
from beembase.operations import Comment
from beem.transactionbuilder import TransactionBuilder

# --- AYARLAR ---
HIVE_NODE = "https://api.hive.blog"
USERNAME = os.getenv("HIVE_USERNAME")
POSTING_KEY = os.getenv("HIVE_POSTING_KEY")
REPO_NAME = os.getenv("REPO_NAME", "hive-bot")

MAIN_TAG = "crypto"
TAGS = ["crypto", "hive", "bitcoin", "data", "news"]

COVER_IMAGE_URL = "https://images.hive.blog/DQmRqpnr8HMfLHTWGbVRBEXgt51Hz1AFQPvLESjZJNdaEch/cover.png"

def get_global_prices():
    try:
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {"ids": "bitcoin,ethereum,solana,hive", "vs_currencies": "usd", "include_24hr_change": "true"}
        return requests.get(url, params=params, timeout=10).json()
    except Exception as e:
        print(f"Global fiyat hatası: {e}")
        return None

def get_hive_engine_data():
    """Hive Engine'den Top 10 (Hacim) ve Top 5 (Fiyat) verilerini çeker - Fallback'li"""
    try:
        url = "https://api.hive-engine.com/rpc/contracts"
        
        # Önce metrics tablosunu dene
        payload = {
            "jsonrpc": "2.0", "id": 1, "method": "find",
            "params": {
                "contract": "market", "table": "metrics", "query": {},
                "limit": 100, "indexes": ["volume", "desc"]
            }
        }
        response = requests.post(url, json=payload, timeout=10).json()
        data = response.get("result", [])
        
        # Hem volume hem price olan tokenları filtrele
        valid_data = [d for d in data if float(d.get("volume", 0)) > 0 and "price" in d and d["price"]]
        
        # Eğer metrics boşsa, params tablosunu dene (fallback)
        if not valid_data:
            print("️ Metrics tablosu boş, params tablosu deneniyor...")
            payload2 = {
                "jsonrpc": "2.0", "id": 2, "method": "find",
                "params": {
                    "contract": "market", "table": "params", "query": {},
                    "limit": 100
                }
            }
            response2 = requests.post(url, json=payload2, timeout=10).json()
            data2 = response2.get("result", [])
            # params tablosundan symbol ve son fiyat bilgilerini al
            valid_data = [d for d in data2 if "symbol" in d]
        
        if not valid_data:
            print("️ Hive Engine verisi alınamadı, boş tablo gösterilecek")
            return [], []
        
        top_10_volume = sorted(valid_data, key=lambda x: float(x.get("volume", 0)), reverse=True)[:10]
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
        print(f"Trending etiket hatası: {e}")
        return ["crypto", "hive", "art", "gaming", "finance"]

def get_crypto_news():
    """Birden fazla RSS kaynağından haber çeker (fallback'li)"""
    rss_sources = [
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "https://cointelegraph.com/rss",
        "https://decrypt.co/feed",
        "https://bitcoinmagazine.com/feed"
    ]
    
    for source_url in rss_sources:
        try:
            print(f"  📡 {source_url.split('/')[2]} deneniyor...")
            feed = feedparser.parse(source_url)
            if feed.entries and len(feed.entries) >= 3:
                news_items = []
                for entry in feed.entries[:5]:
                    title = entry.title
                    link = entry.link
                    summary = entry.get('summary', entry.get('description', ''))
                    clean_summary = re.sub(r'<[^>]+>', '', summary)[:120].strip() + "..."
                    news_items.append(f"**[{title}]({link})**\n> {clean_summary}\n")
                print(f"  ✅ {len(news_items)} haber bulundu")
                return news_items
        except Exception as e:
            print(f"  ⚠️ {source_url.split('/')[2]} başarısız: {e}")
            continue
    
    print("⚠️ Hiçbir haber kaynağı çalışmadı")
    return ["*News feed temporarily unavailable. Please check back tomorrow.*"]

def generate_post(global_prices, he_volume, he_price, trending_tags, news):
    today = time.strftime("%B %d, %Y")
    
    # 1. Global Piyasa
    global_md = "| Asset | Price (USD) | 24h Change |\n| :--- | :--- | :--- |\n"
    for coin_id, name in [("bitcoin", "Bitcoin (BTC)"), ("ethereum", "Ethereum (ETH)"), ("solana", "Solana (SOL)"), ("hive", "Hive (HIVE)")]:
        if coin_id in global_prices:
            p = global_prices[coin_id]
            emoji = "🟢" if p['usd_24h_change'] >= 0 else ""
            global_md += f"| **{name}** | ${p['usd']:,.4f} | {emoji} {p['usd_24h_change']:.2f}% |\n"

    # 2. Hive Engine Hacim (boşsa mesaj göster)
    if he_volume:
        he_vol_md = "| Rank | Token | Volume (24h) |\n| :--- | :--- | :--- |\n"
        for i, token in enumerate(he_volume, 1):
            vol = float(token.get("volume", 0))
            he_vol_md += f"| {i} | **{token['symbol']}** | ${vol:,.2f} |\n"
    else:
        he_vol_md = "*Hive Engine volume data temporarily unavailable.*\n"

    # 3. Hive Engine Fiyat (boşsa mesaj göster)
    if he_price:
        he_price_md = "| Rank | Token | Price (HIVE) |\n| :--- | :--- | :--- |\n"
        for i, token in enumerate(he_price, 1):
            he_price_md += f"| {i} | **{token['symbol']}** | {float(token['price']):,.4f} |\n"
    else:
        he_price_md = "*Hive Engine price data temporarily unavailable.*\n"

    # 4. Trending Tags
    tags_md = ", ".join([f"`#{tag}`" for tag in trending_tags])

    # 5. Haberler
    news_md = "\n".join([f"{i+1}. {item}" for i, item in enumerate(news)])

    content = f"""![Daily Market Pulse]({COVER_IMAGE_URL})

# Daily Market Pulse: Crypto, Hive Engine & Top News | {today}

Hello Hive Community! 👋

Welcome to your daily data brief. No fluff and no opinions, just the raw numbers from the global crypto markets, the Hive Engine ecosystem and the top news of the day.

---

### 🌍 1. Global Market Overview

{global_md}

---

### 🐝 2. Hive Engine Top 10 (By 24h Volume)

{he_vol_md}

---

### 💎 3. Hive Engine Top 5 (Highest Priced)

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
    """Postu Hive blockchain'e gönderir"""
    try:
        hive = Hive(node=HIVE_NODE, nobroadcast=False)
        permlink = f"daily-market-pulse-{time.strftime('%Y-%m-%d')}"
        json_metadata = json.dumps({"tags": TAGS, "app": "hive-daily-pulse/1.0"})
        
        print("📡 Publishing to Hive...")
        
        op = Comment(
            parent_author="",
            parent_permlink=MAIN_TAG,
            author=USERNAME,
            permlink=permlink,
            title=title,
            body=body,
            json_metadata=json_metadata
        )
        
        tx = TransactionBuilder(blockchain_instance=hive)
        tx.appendOps(op)
        tx.appendWif(POSTING_KEY)
        tx.sign()
        response = tx.broadcast()
        
        # DÜZELTME: "id" yerine "signatures" kontrol et (Hive node böyle döndürüyor)
        if response and isinstance(response, dict) and "signatures" in response:
            print(f"✅ SUCCESSFULLY PUBLISHED!")
            print(f"🔗 Link: https://hive.blog/{MAIN_TAG}/@{USERNAME}/{permlink}")
        else:
            print(f"⚠️ Blockchain yanıtı alındı ama format beklenmedik: {type(response)}")
            if response:
                print(f"   Yanıt anahtarları: {list(response.keys()) if isinstance(response, dict) else 'dict değil'}")
            
    except Exception as e:
        print(f"❌ Publishing Error: {e}")
        import traceback
        traceback.print_exc()

def main():
    print("=" * 60)
    print("🐝 Hive Daily Market Pulse Bot Starting...")
    print("=" * 60)
    
    if not USERNAME or not POSTING_KEY:
        print("❌ ERROR: HIVE_USERNAME or HIVE_POSTING_KEY is missing!")
        return
    
    print("📡 Fetching Global Prices...")
    prices = get_global_prices()
    if not prices:
        print("❌ Global prices failed. Aborting.")
        return
    
    print("📡 Fetching Hive Engine Data...")
    he_vol, he_price = get_hive_engine_data()
    print(f"   Volume tokens: {len(he_vol)}, Price tokens: {len(he_price)}")
    
    print("📡 Fetching Trending Tags...")
    tags = get_trending_tags()
    print(f"   Found {len(tags)} tags: {tags}")
    
    print("📡 Fetching Crypto News...")
    news = get_crypto_news()
    print(f"   Found {len(news)} news items")
    
    print("📝 Generating Post Content...")
    title, body = generate_post(prices, he_vol, he_price, tags, news)
    
    print(" Publishing...")
    publish_post(title, body)
    print("=" * 60)
    print("✅ Bot finished successfully!")

if __name__ == "__main__":
    main()
