# =============================================================
# backend.py — Price Passport core logic
# Bloomberg Hackathon: "Purchasing Power" Travel Arbitrage Tool
# =============================================================
# This module has NO input() calls and NO __main__ demo block —
# it's meant to be imported by app.py (the Flask server).
# Keep your Colab notebook as-is for testing; this is the
# production version that the web UI actually calls.

import os
import requests
import json
import time

# -------------------------------------------------------------
# API KEYS — set these as environment variables, NOT hardcoded.
# In your terminal before running: 
#   export SERPAPI_KEY="your_key_here"
#   export GEMINI_API_KEY="your_key_here"
# This keeps keys out of your codebase (and out of anything you
# might commit to GitHub or share for judging).
# -------------------------------------------------------------
SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-3.5-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
SERPAPI_URL = "https://serpapi.com/search.json"

# -------------------------------------------------------------
# STATIC DATA: consumption tax + tourist refund rules per country
# -------------------------------------------------------------
# Keys here match the frontend's COUNTRY_DATA keys exactly
# (FR instead of EU, no CN — matches what we tested working).
COUNTRY_RULES = {
    "US": {
        "currency": "USD",
        "tax_rate": 0.09,
        "tourist_refund": 0.0,
        "anchor_city": "New York / LA",
        "source_note": "No federal VAT; state sales tax only, no tourist refund.",
        "gl_code": "us",
        "hl_code": "en",
        "min_purchase": None,
    },
    "FR": {
        "currency": "EUR",
        "tax_rate": 0.20,
        "tourist_refund": 0.14,
        "anchor_city": "Paris / Berlin",
        "source_note": "~20% VAT, ~4% refund processing fee, min purchase varies (e.g. EUR100 in France).",
        "gl_code": "fr",
        "hl_code": "fr",
        "min_purchase": 100,  # EUR
    },
    "JP": {
        "currency": "JPY",
        "tax_rate": 0.10,
        "tourist_refund": 0.10,
        "anchor_city": "Tokyo",
        "source_note": "10% consumption tax, full tourist refund, min JPY5000/store/day.",
        "gl_code": "jp",
        "hl_code": "ja",
        "min_purchase": 5000,
    },
    "GB": {
        "currency": "GBP",
        "tax_rate": 0.20,
        "tourist_refund": 0.0,
        "anchor_city": "London",
        "source_note": "20% VAT but tourist refund scheme discontinued after Brexit.",
        "gl_code": "uk",
        "hl_code": "en",
        "min_purchase": None,
    },
    "IN": {
        "currency": "INR",
        "tax_rate": 0.18,
        "tourist_refund": 0.0,
        "anchor_city": "Mumbai / Delhi",
        "source_note": "18% GST on electronics; no functioning tourist refund in practice.",
        "gl_code": "in",
        "hl_code": "en",
        "min_purchase": None,
    },
    "CA": {
        "currency": "CAD",
        "tax_rate": 0.13,
        "tourist_refund": 0.0,
        "anchor_city": "Toronto",
        "source_note": "13% HST (Ontario); tourist rebate program abolished in 2007.",
        "gl_code": "ca",
        "hl_code": "en",
        "min_purchase": None,
    },
    "BR": {
        "currency": "BRL",
        "tax_rate": 0.18,
        "tourist_refund": 0.0,
        "anchor_city": "Rio de Janeiro",
        "source_note": "No unified VAT; state ICMS ~17-18% plus steep import duties on electronics; no tourist refund.",
        "gl_code": "br",
        "hl_code": "pt-br",
        "min_purchase": None,
    },
    "MX": {
        "currency": "MXN",
        "tax_rate": 0.16,
        "tourist_refund": 0.0,
        "anchor_city": "Mexico City",
        "source_note": "16% IVA; refund scheme exists but not reliably usable by tourists.",
        "gl_code": "mx",
        "hl_code": "es",
        "min_purchase": None,
    },
    "KR": {
        "currency": "KRW",
        "tax_rate": 0.10,
        "tourist_refund": 0.07,
        "anchor_city": "Seoul",
        "source_note": "10% VAT, ~7% effective instant refund at registered stores.",
        "gl_code": "kr",
        "hl_code": "ko",
        "min_purchase": 30000,
    },
}


# -------------------------------------------------------------
# LIVE DATA: FX rates via Frankfurter API
# -------------------------------------------------------------
def get_fx_rates(base_currency="USD"):
    url = f"https://api.frankfurter.app/latest?from={base_currency}"
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    return response.json()["rates"]


def convert_to_base(amount, from_currency, base_currency, fx_rates):
    if from_currency == base_currency:
        return amount
    rate = fx_rates[from_currency]
    return amount / rate


# =============================================================
# Core calculation logic
# =============================================================
def calculate_effective_price(item_name, spec_note, home_country, home_price, itinerary):
    """
    itinerary: list of dicts like {"country": "JP", "local_price": 368000}
    Returns a dict with 'results' (ranked list) and 'recommendation' (string).
    """
    home_currency = COUNTRY_RULES[home_country]["currency"]
    fx_rates = get_fx_rates(home_currency)

    results = [{
        "country": home_country,
        "location_label": COUNTRY_RULES[home_country]["anchor_city"],
        "local_price": home_price,
        "local_currency": home_currency,
        "converted_price": home_price,
        "refund_applied": 0.0,
        "effective_price": home_price,
        "is_home": True,
    }]

    for stop in itinerary:
        country = stop["country"]
        local_price = stop["local_price"]
        rules = COUNTRY_RULES[country]
        local_currency = rules["currency"]
        min_purchase = rules.get("min_purchase")

        converted_price = convert_to_base(local_price, local_currency, home_currency, fx_rates)

        meets_threshold = (min_purchase is None) or (local_price >= min_purchase)
        refund_rate = rules["tourist_refund"] if meets_threshold else 0.0
        refund_amount = converted_price * refund_rate
        effective_price = converted_price - refund_amount

        results.append({
            "country": country,
            "location_label": rules["anchor_city"],
            "local_price": local_price,
            "local_currency": local_currency,
            "converted_price": converted_price,
            "refund_applied": refund_amount,
            "refund_eligible": meets_threshold and rules["tourist_refund"] > 0,
            "min_purchase": min_purchase,
            "effective_price": effective_price,
            "is_home": False,
            "date": stop.get("date"),
        })

    results.sort(key=lambda r: r["effective_price"])

    best = results[0]
    home_entry = next(r for r in results if r["is_home"])
    savings = home_entry["effective_price"] - best["effective_price"]
    savings_pct = (savings / home_entry["effective_price"]) * 100 if home_entry["effective_price"] else 0

    if best["is_home"]:
        recommendation = (
            f"Buy {item_name} now at home ({home_entry['location_label']}) — "
            f"nothing on your itinerary beats {home_entry['effective_price']:.2f} {home_currency}."
        )
    else:
        recommendation = (
            f"Wait to buy {item_name} in {best['location_label']} — "
            f"effective price {best['effective_price']:.2f} {home_currency} "
            f"saves you {savings:.2f} {home_currency} ({savings_pct:.1f}%) vs. buying at home."
        )

    return {
        "item": item_name,
        "spec_note": spec_note,
        "home_currency": home_currency,
        "results": results,
        "recommendation": recommendation,
    }


# =============================================================
# Live product price lookup via SerpApi (Google Shopping)
# =============================================================
def search_product_listings(item_name, country_key, api_key=None, num_results=5):
    api_key = api_key or SERPAPI_KEY
    gl_code = COUNTRY_RULES[country_key]["gl_code"]
    hl_code = COUNTRY_RULES[country_key]["hl_code"]

    params = {
        "engine": "google_shopping",
        "q": item_name,
        "gl": gl_code,
        "hl": hl_code,
        "api_key": api_key,
    }

    response = requests.get(SERPAPI_URL, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()
    shopping_results = data.get("shopping_results", [])[:num_results]

    if not shopping_results:
        # Some gl/hl combos intermittently return empty — retry without hl
        fallback_params = {k: v for k, v in params.items() if k != "hl"}
        response = requests.get(SERPAPI_URL, params=fallback_params, timeout=30)
        response.raise_for_status()
        data = response.json()
        shopping_results = data.get("shopping_results", [])[:num_results]

    listings = []
    for item in shopping_results:
        listings.append({
            "title": item.get("title"),
            "price_str": item.get("price"),
            "extracted_price": item.get("extracted_price"),
            "source": item.get("source"),
            "link": item.get("link") or item.get("product_link"),
        })

    return listings


# =============================================================
# LLM filtering of listings via Gemini API
# =============================================================
GEMINI_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "classifications": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "flag": {
                        "type": "string",
                        "enum": ["MATCH", "ACCESSORY", "BUNDLE", "SUSPICIOUS"],
                    },
                    "reason": {"type": "string"},
                },
                "required": ["index", "flag", "reason"],
            },
        }
    },
    "required": ["classifications"],
}


def filter_listings_with_gemini(listings, item_name, spec_note, api_key=None):
    api_key = api_key or GEMINI_API_KEY
    if not listings:
        return listings

    listings_text = "\n".join(
        f"{i}: title=\"{l['title']}\", price=\"{l['price_str']}\", seller=\"{l['source']}\""
        for i, l in enumerate(listings)
    )

    prompt = f"""You are screening Google Shopping search results for a price-comparison tool.

Target product: "{item_name}" ({spec_note})

For each listing, classify it as one of:
- MATCH: the actual full/complete product at a plausible retail price
- ACCESSORY: a related accessory or add-on, not the main product itself
- BUNDLE: includes extra items (games, cases, etc.) bundled in, inflating the price
- SUSPICIOUS: price is unrealistically low/high for this product, or the seller/domain looks untrustworthy

Listings:
{listings_text}

Classify every index from 0 to {len(listings) - 1}."""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": GEMINI_RESPONSE_SCHEMA,
            "temperature": 0.1,
        },
    }
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}

    for attempt in range(2):
        try:
            response = requests.post(GEMINI_URL, headers=headers, json=payload, timeout=45)
            response.raise_for_status()
            data = response.json()

            raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
            parsed = json.loads(raw_text)

            flags_by_index = {c["index"]: c for c in parsed["classifications"]}
            for i, listing in enumerate(listings):
                c = flags_by_index.get(i, {"flag": "SUSPICIOUS", "reason": "No classification returned"})
                listing["ai_flag"] = c["flag"]
                listing["ai_reason"] = c["reason"]
            return listings

        except (requests.exceptions.RequestException, KeyError, json.JSONDecodeError):
            if attempt == 0:
                time.sleep(3)
                continue
            for listing in listings:
                listing["ai_flag"] = "UNSCREENED"
                listing["ai_reason"] = "AI screening failed — review manually"

    return listings
