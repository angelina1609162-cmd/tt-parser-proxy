from flask import Flask, request, jsonify, Response

app = Flask(__name__)

HTML_PAGE = """<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>TT Parser Proxy</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {
            background: #0e0e0e;
            color: #eaeaea;
            font-family: Arial, sans-serif;
            padding: 20px;
        }
        h1 { color: #4caf50; }
        input, button {
            padding: 10px;
            margin: 5px 0;
            width: 100%;
            font-size: 16px;
        }
        button {
            background: #4caf50;
            border: none;
            cursor: pointer;
        }
        pre {
            background: #111;
            padding: 10px;
            overflow-x: auto;
        }
    </style>
</head>
<body>
    <h1>TT Parser Proxy</h1>
    <p>Введите фамилии игроков:</p>

    <input id="p1" placeholder="Игрок 1">
    <input id="p2" placeholder="Игрок 2">
    <button onclick="search()">Искать</button>

    <pre id="out"></pre>

<script>
async function search() {
    const p1 = document.getElementById('p1').value;
    const p2 = document.getElementById('p2').value;

    const res = await fetch(`/api/search?p1=${encodeURIComponent(p1)}&p2=${encodeURIComponent(p2)}`);
    const data = await res.json();
    document.getElementById('out').textContent = JSON.stringify(data, null, 2);
}
</script>
</body>
</html>
"""

@app.route("/", methods=["GET"])
def index():
    return Response(HTML_PAGE, mimetype="text/html")

@app.route("/api/search", methods=["GET"])
def api_search():
    p1 = request.args.get("p1", "")
    p2 = request.args.get("p2", "")

    return jsonify({
        "status": "ok",
        "player1": p1,
        "player2": p2,
        "sources": [
            "flashscore",
            "sofascore",
            "aiscore",
            "score24",
            "betcity"
        ],
        "matches": []
    })
