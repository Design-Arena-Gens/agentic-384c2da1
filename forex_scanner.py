#!/usr/bin/env python3
"""
Forex Scanner script that fetches live exchange rates from the Alpha Vantage API.

Usage examples:
    python forex_scanner.py --pairs EUR/USD GBP/USD USD/JPY
    python forex_scanner.py --pairs EUR/USD --output json
    ALPHAVANTAGE_API_KEY=demo python forex_scanner.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import requests
except ImportError as exc:  # pragma: no cover - handled at runtime
    raise SystemExit(
        "Missing dependency 'requests'. Install with 'pip install -r requirements.txt'."
    ) from exc


ALPHAVANTAGE_API_URL = "https://www.alphavantage.co/query"
API_FUNCTION = "CURRENCY_EXCHANGE_RATE"
DEFAULT_PAIRS = ("EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD")
ENV_API_KEY = "ALPHAVANTAGE_API_KEY"


class ForexScannerError(Exception):
    """Domain-specific exception for scanner errors."""


@dataclass
class ExchangeRate:
    from_currency: str
    to_currency: str
    rate: float
    last_refreshed: str
    bid_price: Optional[float]
    ask_price: Optional[float]

    @classmethod
    def from_api(cls, payload: Dict[str, str]) -> "ExchangeRate":
        try:
            from_code = payload["1. From_Currency Code"]
            to_code = payload["3. To_Currency Code"]
            rate = float(payload["5. Exchange Rate"])
            last_refreshed = payload["6. Last Refreshed"]
            bid_price = cls._parse_optional_float(payload.get("8. Bid Price"))
            ask_price = cls._parse_optional_float(payload.get("9. Ask Price"))
        except KeyError as exc:
            raise ForexScannerError(f"Response missing field: {exc}") from exc
        except ValueError as exc:
            raise ForexScannerError(f"Invalid numeric value in response: {exc}") from exc
        return cls(
            from_currency=from_code,
            to_currency=to_code,
            rate=rate,
            last_refreshed=last_refreshed,
            bid_price=bid_price,
            ask_price=ask_price,
        )

    @staticmethod
    def _parse_optional_float(value: Optional[str]) -> Optional[float]:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except ValueError:
            return None


def parse_pairs(pairs: Sequence[str]) -> List[Tuple[str, str]]:
    normalized_pairs = []
    for raw in pairs:
        cleaned = raw.replace("-", "/").strip().upper()
        if "/" not in cleaned:
            raise ForexScannerError(
                f"Invalid pair '{raw}'. Use the format BASE/QUOTE (e.g., EUR/USD)."
            )
        base, quote = cleaned.split("/", 1)
        if not base or not quote:
            raise ForexScannerError(
                f"Invalid pair '{raw}'. Both base and quote currencies are required."
            )
        normalized_pairs.append((base, quote))
    return normalized_pairs


def fetch_exchange_rate(
    api_key: str, base: str, quote: str, *, timeout: int = 10
) -> ExchangeRate:
    params = {
        "function": API_FUNCTION,
        "from_currency": base,
        "to_currency": quote,
        "apikey": api_key,
    }
    try:
        response = requests.get(ALPHAVANTAGE_API_URL, params=params, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise ForexScannerError(
            f"Network error while fetching {base}/{quote}: {exc}"
        ) from exc

    payload = response.json()
    if "Error Message" in payload:
        raise ForexScannerError(
            f"API error for {base}/{quote}: {payload['Error Message']}"
        )
    if "Note" in payload:
        raise ForexScannerError(
            f"API limit reached: {payload['Note']} (pair {base}/{quote})."
        )
    data_key = "Realtime Currency Exchange Rate"
    if data_key not in payload:
        raise ForexScannerError(
            f"Unexpected response structure for {base}/{quote}: {json.dumps(payload)}"
        )
    return ExchangeRate.from_api(payload[data_key])


def run_scanner(
    pairs: Sequence[Tuple[str, str]],
    api_key: Optional[str],
    *,
    retry: int,
    retry_delay: float,
) -> List[ExchangeRate]:
    if not api_key:
        raise ForexScannerError(
            f"Missing API key. Set the {ENV_API_KEY} environment variable or "
            "provide --api-key."
        )

    results: List[ExchangeRate] = []
    for base, quote in pairs:
        attempt = 0
        while True:
            try:
                rate = fetch_exchange_rate(api_key, base, quote)
                results.append(rate)
                break
            except ForexScannerError as exc:
                attempt += 1
                if attempt > retry:
                    raise
                time.sleep(retry_delay)
    return results


def render_table(data: Iterable[ExchangeRate]) -> str:
    headers = (
        ("Pair", max(4, max((len(f"{item.from_currency}/{item.to_currency}") for item in data), default=4))),
        ("Rate", 12),
        ("Bid", 12),
        ("Ask", 12),
        ("Last Refreshed", 19),
    )
    column_widths = {name: width for name, width in headers}
    header_line = " | ".join(f"{name:<{column_widths[name]}}" for name, _ in headers)
    separator = "-+-".join("-" * column_widths[name] for name, _ in headers)

    rows = []
    for item in data:
        pair = f"{item.from_currency}/{item.to_currency}"
        rows.append(
            " | ".join(
                (
                    f"{pair:<{column_widths['Pair']}}",
                    f"{item.rate:<{column_widths['Rate']}.6f}",
                    f"{format_price(item.bid_price, column_widths['Bid'])}",
                    f"{format_price(item.ask_price, column_widths['Ask'])}",
                    f"{item.last_refreshed:<{column_widths['Last Refreshed']}}",
                )
            )
        )
    return "\n".join((header_line, separator, *rows))


def format_price(value: Optional[float], width: int) -> str:
    return f"{value:<{width}.6f}" if value is not None else f"{'—':<{width}}"


def save_output(path: str, payload: Dict[str, object]) -> None:
    with open(path, "w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2)


def load_demo_data(pairs: Sequence[Tuple[str, str]]) -> List[ExchangeRate]:
    demo_payload: Dict[str, Dict[str, str]] = {
        "EUR/USD": {
            "1. From_Currency Code": "EUR",
            "3. To_Currency Code": "USD",
            "5. Exchange Rate": "1.08650",
            "6. Last Refreshed": "2024-05-01 15:35:00",
            "8. Bid Price": "1.08630",
            "9. Ask Price": "1.08670",
        },
        "GBP/USD": {
            "1. From_Currency Code": "GBP",
            "3. To_Currency Code": "USD",
            "5. Exchange Rate": "1.24510",
            "6. Last Refreshed": "2024-05-01 15:35:00",
            "8. Bid Price": "1.24490",
            "9. Ask Price": "1.24530",
        },
        "USD/JPY": {
            "1. From_Currency Code": "USD",
            "3. To_Currency Code": "JPY",
            "5. Exchange Rate": "154.8200",
            "6. Last Refreshed": "2024-05-01 15:35:00",
            "8. Bid Price": "154.7800",
            "9. Ask Price": "154.8600",
        },
        "USD/CHF": {
            "1. From_Currency Code": "USD",
            "3. To_Currency Code": "CHF",
            "5. Exchange Rate": "0.90680",
            "6. Last Refreshed": "2024-05-01 15:35:00",
            "8. Bid Price": "0.90660",
            "9. Ask Price": "0.90700",
        },
        "AUD/USD": {
            "1. From_Currency Code": "AUD",
            "3. To_Currency Code": "USD",
            "5. Exchange Rate": "0.65320",
            "6. Last Refreshed": "2024-05-01 15:35:00",
            "8. Bid Price": "0.65300",
            "9. Ask Price": "0.65340",
        },
    }
    results = []
    for base, quote in pairs:
        key = f"{base}/{quote}"
        if key not in demo_payload:
            raise ForexScannerError(
                f"Demo data for {key} is unavailable. Try a default currency pair."
            )
        results.append(ExchangeRate.from_api(demo_payload[key]))
    return results


def parse_arguments(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch live forex exchange rates using the Alpha Vantage API.",
        epilog="Alpha Vantage free tier allows 25 requests/day and 5 requests/minute.",
    )
    parser.add_argument(
        "--pairs",
        nargs="+",
        default=DEFAULT_PAIRS,
        metavar="BASE/QUOTE",
        help="Currency pairs to scan (default: %(default)s).",
    )
    parser.add_argument(
        "--api-key",
        help=(
            f"Alpha Vantage API key. Overrides the {ENV_API_KEY} environment variable."
        ),
    )
    parser.add_argument(
        "--output",
        choices=("table", "json"),
        default="table",
        help="Output format (default: table).",
    )
    parser.add_argument(
        "--save",
        metavar="PATH",
        help="Optional path to save the raw JSON payload.",
    )
    parser.add_argument(
        "--retry",
        type=int,
        default=1,
        help="Number of retries per pair on API failure (default: 1).",
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=5.0,
        help="Seconds to wait between retries (default: 5).",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Use bundled demo data instead of calling the live API.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_arguments(argv)
    try:
        pairs = parse_pairs(args.pairs)
        if args.demo:
            rates = load_demo_data(pairs)
        else:
            api_key = args.api_key or os.getenv(ENV_API_KEY)
            rates = run_scanner(
                pairs,
                api_key,
                retry=max(0, args.retry),
                retry_delay=max(0.5, args.retry_delay),
            )
        if args.output == "json":
            payload = [
                {
                    "pair": f"{rate.from_currency}/{rate.to_currency}",
                    "rate": rate.rate,
                    "bid": rate.bid_price,
                    "ask": rate.ask_price,
                    "last_refreshed": rate.last_refreshed,
                }
                for rate in rates
            ]
            print(json.dumps(payload, indent=2))
        else:
            print(render_table(rates))
        if args.save:
            payload = {
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "pairs": [f"{base}/{quote}" for base, quote in pairs],
                "data": [
                    {
                        "from_currency": rate.from_currency,
                        "to_currency": rate.to_currency,
                        "exchange_rate": rate.rate,
                        "bid_price": rate.bid_price,
                        "ask_price": rate.ask_price,
                        "last_refreshed": rate.last_refreshed,
                    }
                    for rate in rates
                ],
            }
            save_output(args.save, payload)
    except ForexScannerError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
