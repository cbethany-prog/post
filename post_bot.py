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

# DRY_RUN=1 ise post Hive'a gönderilmez, sadece ekrana/dosyaya yazılır
DRY_RUN = os.getenv("DRY_RUN", "").strip().lower() in ("1", "true", "yes")

MAIN_TAG = "crypto"
TAGS = ["crypto", "hive", "pimp", "hive-engine", "proofofbrain", "news", "inleo", "leo", "cent", "tribes"]

# Sabit Kapak Görseli URL'i (f harfine gerek yok)
COVER_IMAGE_URL = "https://images.hive.blog/DQmR32tQbfZ3Jj3wJSjeDuYyTnkCRiPgmNbzbbEcSgfrwoy/cover.png"

def get_global_prices():
    """CoinGecko'dan global fiyatları çeker"""
    try:
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {"ids": "bitcoin,ethereum,solana,hive", "vs_currencies": "usd", "include_24hr_change": "true"}
        return requests.get(url, params=params, timeout=10).json()
    except Exception as e:
        print(f"Global fiyat hatası: {e}")
        return None

HIVE_API_NODES = [
    "https://api.hive.blog",
    "https://api.deathwing.me",
    "https://hive-api.arcange.eu",
]

def _fetch_trending_posts():
    """Trending postları çeker. Önce bridge API, olmazsa condenser API dener."""
    attempts = [
        ("bridge.get_ranked_posts", {"sort": "trending", "tag": "", "limit": 30}),
        ("condenser_api.get_discussions_by_trending", [{"tag": "", "limit": 30}]),
    ]
    for node in HIVE_API_NODES:
        for method, params in attempts:
            try:
                payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
                resp = requests.post(node, json=payload, timeout=15)
                data = resp.json()
                if "error" in data:
                    print(f"   ⚠️ {node.split('/')[2]} {method} hata: {str(data['error'])[:150]}")
                    continue
                posts = data.get("result") or []
                if posts:
                    print(f"   ✅ {node.split('/')[2]} {method}: {len(posts)} post")
                    return posts
                print(f"   ⚠️ {node.split('/')[2]} {method}: boş sonuç")
            except Exception as e:
                print(f"   ⚠️ {node.split('/')[2]} {method} başarısız: {e}")
    return []

def get_trending_tags():
    """Hive'daki güncel trending postlardan en çok kullanılan 5 etiketi bulur"""
    try:
        posts = _fetch_trending_posts()

        tag_counter = Counter()
        for post in posts:
            meta = post.get("json_metadata") or {}
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}
            tags = meta.get("tags", []) if isinstance(meta, dict) else []

            # Aynı post içinde tekrar eden etiketi bir kez say (sırayı koru)
            clean = dict.fromkeys(
                t.strip().lower() for t in tags if isinstance(t, str) and t.strip()
            )
            for tag in clean:
                # Ana etiketi ve topluluk kodlarını (hive-123456) hariç tut
                if tag == MAIN_TAG or re.match(r"^hive-\d+$", tag):
                    continue
                tag_counter[tag] += 1

        return [tag for tag, _ in tag_counter.most_common(5)]
    except Exception as e:
        print(f"Trending etiket hatası: {e}")
        return []  # Boş dönerse post içinde bu bölüm gösterilmez

HIVE_ENGINE_NODES = [
    "https://api.hive-engine.com/rpc/contracts",
    "https://herpc.dtools.dev/contracts",
    "https://engine.rishipanthee.com/contracts",
]

def _fmt_price(x):
    """Küçük fiyatlarda daha fazla basamak gösterir"""
    if x >= 1:
        return f"{x:,.4f}"
    if x >= 0.01:
        return f"{x:.5f}"
    return f"{x:.8f}"

def _valid_ts(ts, now):
    """Expiration alanı (saniye veya ms) hala geçerli mi?"""
    try:
        ts = float(ts)
    except (TypeError, ValueError):
        return False
    if ts > 1e12:
        ts /= 1000
    return ts > now

def get_hive_engine_tokens(limit=15):
    """Hive-Engine marketinden 24s hacme göre en aktif token'ları çeker"""
    payload = {
        "jsonrpc": "2.0",
        "method": "find",
        "params": {"contract": "market", "table": "metrics", "query": {}, "limit": 1000},
        "id": 1,
    }
    for node in HIVE_ENGINE_NODES:
        try:
            print(f"  📡 {node.split('/')[2]} deneniyor...")
            resp = requests.post(node, json=payload, timeout=20)
            resp.raise_for_status()
            rows = resp.json().get("result") or []
            if not rows:
                continue

            now = time.time()
            tokens = []
            for r in rows:
                symbol = r.get("symbol")
                if not symbol or symbol == "SWAP.HIVE":  # SWAP.HIVE = HIVE'ın kendisi
                    continue
                try:
                    price = float(r.get("lastPrice", 0))
                except (TypeError, ValueError):
                    continue
                if price <= 0:
                    continue

                # 24s hacim (süresi dolmuşsa 0 say)
                try:
                    volume = float(r.get("volume", 0))
                except (TypeError, ValueError):
                    volume = 0.0
                if not _valid_ts(r.get("volumeExpiration"), now):
                    volume = 0.0

                # 24s değişim (dünkü fiyat geçerliyse hesapla)
                change = None
                try:
                    last_day = float(r.get("lastDayPrice", 0))
                    if last_day > 0 and _valid_ts(r.get("lastDayPriceExpiration"), now):
                        change = (price - last_day) / last_day * 100
                except (TypeError, ValueError):
                    pass

                tokens.append({"symbol": symbol, "price": price, "volume": volume, "change": change})

            tokens.sort(key=lambda t: t["volume"], reverse=True)
            top = tokens[:limit]
            if top:
                print(f"  ✅ {len(top)} Hive-Engine token bulundu")
                return top
        except Exception as e:
            print(f"  ⚠️ {node.split('/')[2]} başarısız: {e}")
            continue

    print("⚠️ Hive-Engine verisi alınamadı")
    return []

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

def generate_post(global_prices, trending_tags, news, he_tokens=None):
    """Tüm verileri birleştirip İngilizce Markdown postu oluşturur"""
    today = time.strftime("%B %d, %Y")
    
    # 1. Global Piyasa Tablosu
    global_md = "| Asset | Price (USD) | 24h Change |\n| :--- | :--- | :--- |\n"
    for coin_id, name in [("bitcoin", "Bitcoin (BTC)"), ("ethereum", "Ethereum (ETH)"), ("solana", "Solana (SOL)"), ("hive", "Hive (HIVE)")]:
        if coin_id in global_prices:
            p = global_prices[coin_id]
            emoji = "🟢" if p['usd_24h_change'] >= 0 else "🔴"
            global_md += f"| **{name}** | ${p['usd']:,.4f} | {emoji} {p['usd_24h_change']:.2f}% |\n"

    # 2. Hive-Engine Token Tablosu
    if he_tokens:
        hive_usd = (global_prices.get("hive") or {}).get("usd")
        he_md = "| # | Token | Price (HIVE) | ≈ USD | 24h Change | 24h Volume (HIVE) |\n| :--- | :--- | :--- | :--- | :--- | :--- |\n"
        for i, t in enumerate(he_tokens, 1):
            usd = f"${_fmt_price(t['price'] * hive_usd)}" if hive_usd else "N/A"
            if t["change"] is None:
                change = "—"
            else:
                emoji = "🟢" if t["change"] >= 0 else "🔴"
                change = f"{emoji} {t['change']:.2f}%"
            he_md += f"| {i} | **{t['symbol']}** | {_fmt_price(t['price'])} | {usd} | {change} | {t['volume']:,.2f} |\n"
    else:
        he_md = "*Hive-Engine data is temporarily unavailable today.*"

    # 3. Haberler
    news_md = "\n".join([f"{i+1}. {item}" for i, item in enumerate(news)])

    # Bölümleri sırayla diz; veri yoksa (ör. trending) bölüm hiç eklenmez, numaralar otomatik kayar
    sections = [("🌍", "Global Market Overview", global_md)]
    if trending_tags:
        tags_md = ", ".join([f"`#{tag}`" for tag in trending_tags])
        sections.append(("🔥", "Trending Topics on Hive", tags_md))
    sections.append(("🪙", "Hive-Engine: Top 15 Tokens by 24h Volume", he_md))
    sections.append(("📰", "Top 5 Crypto News of the Day", news_md))

    sections_md = "\n\n---\n\n".join(
        f"### {emoji} {i}. {title}\n\n{text}"
        for i, (emoji, title, text) in enumerate(sections, 1)
    )

    # Tam Metin
    content = f"""![Daily Market Pulse]({COVER_IMAGE_URL})

Hello Hive Community,

Welcome to your daily data brief. No fluff and no opinions, just the raw numbers from the global crypto markets, the Hive ecosystem and the top news of the day.

---

{sections_md}

---

*Note: This report brings together real-time data from public sources like CoinGecko and major crypto news outlets. The information is meant for educational purposes and is not financial advice. Please do your own research.*

What are your thoughts on today's market and news? Let's discuss below 👇
"""
    return f"Daily Market Pulse - Crypto, Hive & Top News | {today}", content

def publish_post(title, body):
    """Postu Hive blockchain'e gönderir (TransactionBuilder ile %100 stabil)"""
    try:
        hive = Hive(node=HIVE_NODE, nobroadcast=False)
        permlink = f"daily-market-pulse-{time.strftime('%Y-%m-%d')}"
        json_metadata = json.dumps({"tags": TAGS, "app": "hiveblog/0.1"})
        
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
        
        if response and isinstance(response, dict) and "signatures" in response:
            print(f"✅ SUCCESSFULLY PUBLISHED!")
            print(f"🔗 Link: https://hive.blog/{MAIN_TAG}/@{USERNAME}/{permlink}")
        else:
            print(f"⚠️ Blockchain yanıtı alındı ama format beklenmedik.")
            
    except Exception as e:
        print(f"❌ Publishing Error: {e}")
        import traceback
        traceback.print_exc()

def main():
    print("=" * 60)
    print("🐝 Hive Daily Market Pulse Bot Starting...")
    print("=" * 60)
    
    if DRY_RUN:
        print("🧪 DRY RUN modu: post Hive'a GÖNDERİLMEYECEK")

    if not DRY_RUN and (not USERNAME or not POSTING_KEY):
        print("❌ ERROR: HIVE_USERNAME or HIVE_POSTING_KEY is missing!")
        return
    
    print("📡 Fetching Global Prices...")
    prices = get_global_prices()
    if not prices:
        print("❌ Global prices failed. Aborting.")
        return
    
    print("📡 Fetching Trending Tags...")
    tags = get_trending_tags()
    print(f"   Found {len(tags)} tags: {tags}")
    
    print("📡 Fetching Hive-Engine Tokens...")
    he_tokens = get_hive_engine_tokens()

    print("📡 Fetching Crypto News...")
    news = get_crypto_news()
    print(f"   Found {len(news)} news items")
    
    print("📝 Generating Post Content...")
    title, body = generate_post(prices, tags, news, he_tokens)
    
    if DRY_RUN:
        print("\n" + "=" * 60)
        print(f"TITLE: {title}")
        print("=" * 60)
        print(body)
        print("=" * 60)
        with open("preview.md", "w", encoding="utf-8") as f:
            f.write(body)
        # GitHub Actions'ta özet sayfasında markdown olarak görünür
        summary_path = os.getenv("GITHUB_STEP_SUMMARY")
        if summary_path:
            with open(summary_path, "a", encoding="utf-8") as f:
                f.write(f"## 🧪 DRY RUN - {title}\n\n---\n\n{body}\n")
        print("🧪 DRY RUN bitti, Hive'a gönderilmedi.")
        return

    print("🚀 Publishing...")
    publish_post(title, body)
    print("=" * 60)
    print("✅ Bot finished successfully!")

if __name__ == "__main__":
    main()
