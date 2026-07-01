import requests

def get_symbols():
    url = "https://api.binance.com/api/v3/exchangeInfo"
    data = requests.get(url, timeout=20).json()

    print("DEBUG:", type(data), data.keys() if isinstance(data, dict) else data)

    return []

def main():
    get_symbols()
    print("RUN OK")

if __name__ == "__main__":
    main()
