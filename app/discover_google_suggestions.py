import json
import urllib.parse
import urllib.request
from pathlib import Path
from datetime import datetime, timezone


SOFIA_ROOT = Path(__file__).resolve().parents[1]

WORKSPACE_ID = "local.ao"
LOCAL_SITE_PATH = SOFIA_ROOT / "sites" / "local_sites" / "ao"

PROFILE_FILE = LOCAL_SITE_PATH / "local_intelligence_profile.json"
SIGNALS_FILE = LOCAL_SITE_PATH / "external_signals.json"


GOOGLE_SUGGEST_URL = "https://suggestqueries.google.com/complete/search"


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def get_next_signal_id(signals: list, country_code: str) -> str:
    max_num = 0

    prefix = f"SIG-{country_code}-"

    for signal in signals:
        signal_id = signal.get("id", "")
        if signal_id.startswith(prefix):
            try:
                num = int(signal_id.replace(prefix, ""))
                max_num = max(max_num, num)
            except ValueError:
                continue

    return f"{prefix}{max_num + 1:03d}"


def signal_exists(signals: list, raw_signal: str, source_detail: str) -> bool:
    raw_signal_normalized = raw_signal.strip().lower()

    for signal in signals:
        if (
            signal.get("raw_signal", "").strip().lower() == raw_signal_normalized
            and signal.get("source_detail") == source_detail
        ):
            return True

    return False


def fetch_google_suggestions(query: str, language: str = "pt") -> list:
    params = {
        "client": "firefox",
        "q": query,
        "hl": language
    }

    url = GOOGLE_SUGGEST_URL + "?" + urllib.parse.urlencode(params)

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 Sofia External Intelligence"
        }
    )

    with urllib.request.urlopen(request, timeout=10) as response:
        data = json.loads(response.read().decode("utf-8"))

    if isinstance(data, list) and len(data) > 1 and isinstance(data[1], list):
        return data[1]

    return []


def main():
    print("=== Sofia: Discover Google Suggestions ===\n")

    profile = load_json(PROFILE_FILE)
    signals_data = load_json(SIGNALS_FILE)

    country_code = profile.get("country", {}).get("code", "AO")
    language = profile.get("country", {}).get("primary_language", "pt")
    seed_keywords = profile.get("search_seed_keywords", [])

    signals = signals_data.get("signals", [])

    if not seed_keywords:
        print("No search_seed_keywords found in local_intelligence_profile.json")
        return

    created_count = 0

    for seed in seed_keywords:
        print(f"Checking seed: {seed}")

        try:
            suggestions = fetch_google_suggestions(seed, language=language)
        except Exception as e:
            print(f"  Error fetching suggestions for '{seed}': {e}")
            continue

        for suggestion in suggestions:
            if signal_exists(signals, suggestion, "google_suggestions"):
                continue

            signal_id = get_next_signal_id(signals, country_code)

            signal = {
                "id": signal_id,
                "created_at": today(),
                "source": "web_search",
                "source_detail": "google_suggestions",
                "submitted_by": "sofia",
                "language": language,
                "raw_signal": suggestion,
                "country": country_code,
                "status": "new",
                "notes": f"Discovered from Google suggestions using seed keyword: {seed}"
            }

            signals.append(signal)
            created_count += 1

            print(f"  Added signal: {signal_id} - {suggestion}")

    signals_data["signals"] = signals
    save_json(SIGNALS_FILE, signals_data)

    print("\nDiscovery completed.")
    print(f"New signals created: {created_count}")


if __name__ == "__main__":
    main()