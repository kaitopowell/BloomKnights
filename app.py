"""
app.py — Price Passport Flask server

Run with:
    export SERPAPI_KEY="your_key"
    export GEMINI_API_KEY="your_key"
    python app.py

Then open http://localhost:5000 in your browser.
"""

from flask import Flask, request, jsonify, render_template

import backend

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/listings", methods=["POST"])
def api_listings():
    """
    Request body: { "item_name": str, "spec_note": str, "country_code": str }
    Response: { "listings": [ {title, price_str, extracted_price, source,
                                link, ai_flag, ai_reason}, ... ],
                "currency": str }
    """
    data = request.get_json(force=True)
    item_name = data.get("item_name", "").strip()
    spec_note = data.get("spec_note", "").strip()
    country_code = data.get("country_code", "").strip()

    if not item_name or not country_code:
        return jsonify({"error": "item_name and country_code are required"}), 400

    if country_code not in backend.COUNTRY_RULES:
        return jsonify({"error": f"Unknown country_code: {country_code}"}), 400

    try:
        listings = backend.search_product_listings(item_name, country_code)
        listings = backend.filter_listings_with_gemini(listings, item_name, spec_note)

        # MATCH first, same ordering logic as the notebook's print_filtered_listings
        order = {"MATCH": 0, "BUNDLE": 1, "ACCESSORY": 2, "SUSPICIOUS": 3, "UNSCREENED": 4}
        listings.sort(key=lambda l: order.get(l.get("ai_flag"), 9))

        currency = backend.COUNTRY_RULES[country_code]["currency"]
        return jsonify({"listings": listings, "currency": currency})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/calculate", methods=["POST"])
def api_calculate():
    """
    Request body: {
        "item_name": str, "spec_note": str,
        "home_country_code": str, "home_price": number,
        "itinerary": [ {"country_code": str, "local_price": number, "date": str|null}, ... ]
    }
    Response: same shape as backend.calculate_effective_price() returns.
    """
    data = request.get_json(force=True)
    item_name = data.get("item_name", "").strip()
    spec_note = data.get("spec_note", "").strip()
    home_country_code = data.get("home_country_code", "").strip()
    home_price = data.get("home_price")
    itinerary_raw = data.get("itinerary", [])

    if not item_name or not home_country_code or home_price is None:
        return jsonify({"error": "item_name, home_country_code, and home_price are required"}), 400

    if home_country_code not in backend.COUNTRY_RULES:
        return jsonify({"error": f"Unknown home_country_code: {home_country_code}"}), 400

    # Translate frontend's {country_code, local_price} into the shape
    # calculate_effective_price() expects: {country, local_price, date}
    itinerary = []
    for stop in itinerary_raw:
        cc = stop.get("country_code")
        if cc not in backend.COUNTRY_RULES:
            return jsonify({"error": f"Unknown country_code in itinerary: {cc}"}), 400
        itinerary.append({
            "country": cc,
            "local_price": stop.get("local_price"),
            "date": stop.get("date"),
        })

    try:
        result = backend.calculate_effective_price(
            item_name=item_name,
            spec_note=spec_note,
            home_country=home_country_code,
            home_price=float(home_price),
            itinerary=itinerary,
        )
        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
