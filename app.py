from flask import Flask, request, Response
import requests
import os

app = Flask(__name__)

# ===== ROOT CHECK =====
@app.route("/")
def home():
    return "OK", 200


# ===== SIMPLE PROXY =====
@app.route("/proxy")
def proxy():
    url = request.args.get("url")

    if not url:
        return {"error": "url parameter is required"}, 400

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    try:
        r = requests.get(
            url,
            headers=headers,
            timeout=15,
            allow_redirects=True
        )

        excluded_headers = [
            "content-encoding",
            "content-length",
            "transfer-encoding",
            "connection"
        ]

        response_headers = [
            (k, v) for k, v in r.headers.items()
            if k.lower() not in excluded_headers
        ]

        return Response(
            r.content,
            r.status_code,
            response_headers
        )

    except requests.exceptions.RequestException as e:
        return {"error": str(e)}, 500


# ===== RENDER ENTRYPOINT =====
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
