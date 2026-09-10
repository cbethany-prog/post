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
        
        # Hem volume hem price alanı olan tokenları filtrele
        valid_data = [d for d in data if float(d.get("volume", 0)) > 0 and "price" in d and d["price"]]
        
        top_10_volume = valid_data[:10]
        top_5_price = sorted(valid_data, key=lambda x: float(x.get("price", 0)), reverse=True)[:5]
        return top_10_volume, top_5_price
    except Exception as e:
        print(f"Hive Engine veri hatası: {e}")
        return [], []
