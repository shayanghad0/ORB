import MetaTrader5 as mt5
import datetime
import json
import os
from zoneinfo import ZoneInfo

# Use New York time zone for trading day boundaries
NY_TZ = ZoneInfo("America/New_York")


def get_latest_bar_time(symbol):
    """
    Return the UTC datetime of the most recent 1‑minute bar for the given symbol.
    Returns None if no data is available.
    """
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 1)
    if rates is None or len(rates) == 0:
        return None
    # rates[0][0] is the bar's open time in seconds since epoch (UTC)
    return datetime.datetime.fromtimestamp(rates[0][0], tz=datetime.timezone.utc)


def get_day_data(symbol, target_date_ny):
    """
    Fetch 1‑minute OHLCV data for the entire day (midnight to midnight) in New York time.
    target_date_ny is a datetime.date object in the NY time zone.
    Returns a list of dictionaries, each representing one bar with time in NY time (ISO format).
    Returns None if the request fails.
    """
    # Build start and end datetimes in NY time zone
    start_ny = datetime.datetime(
        target_date_ny.year, target_date_ny.month, target_date_ny.day,
        tzinfo=NY_TZ
    )
    end_ny = start_ny + datetime.timedelta(days=1) - datetime.timedelta(seconds=1)

    # Convert to UTC for MetaTrader5
    start_utc = start_ny.astimezone(datetime.timezone.utc)
    end_utc = end_ny.astimezone(datetime.timezone.utc)

    rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M1, start_utc, end_utc)
    if rates is None:
        return None

    data = []
    for rate in rates:
        dt_utc = datetime.datetime.fromtimestamp(rate[0], tz=datetime.timezone.utc)
        dt_ny = dt_utc.astimezone(NY_TZ)
        data.append({
            'time': dt_ny.isoformat(),
            'open': float(rate[1]),
            'high': float(rate[2]),
            'low': float(rate[3]),
            'close': float(rate[4]),
            'tick_volume': int(rate[5]),
            'spread': int(rate[6]),
            'real_volume': int(rate[7])
        })
    return data


def save_day_data(symbol, date_ny, data, output_dir="."):
    """Save a day's data to a JSON file."""
    if not data:
        return
    filename = f"{symbol}_{date_ny.isoformat()}_M1.json"
    filepath = os.path.join(output_dir, filename)
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"Saved {len(data)} bars to '{filepath}'")


def main():
    # Initialize MetaTrader 5
    if not mt5.initialize():
        print("MT5 initialization failed.")
        return
    print("MT5 initialized successfully.")

    # Ask for symbol
    symbol = input("Enter symbol (e.g., XAUUSD): ").strip().upper()
    if not mt5.symbol_info(symbol):
        print(f"Symbol '{symbol}' not found.")
        mt5.shutdown()
        return
    mt5.symbol_select(symbol, True)

    # Ask for number of days to go back (including the most recent day)
    days_str = input("Enter number of days to fetch (e.g., 5): ")
    try:
        days = int(days_str)
        if days <= 0:
            print("Number of days must be positive.")
            mt5.shutdown()
            return
    except ValueError:
        print("Invalid input. Please enter an integer.")
        mt5.shutdown()
        return

    # Optional: ask for output directory
    out_dir = input("Output directory (press Enter for current folder): ").strip()
    if not out_dir:
        out_dir = "."
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)

    # Get the newest available bar time (UTC)
    latest_utc = get_latest_bar_time(symbol)
    if latest_utc is None:
        print(f"No data available for {symbol}.")
        mt5.shutdown()
        return

    # Convert to New York time and compute the range of dates
    latest_ny = latest_utc.astimezone(NY_TZ)
    start_date = (latest_ny - datetime.timedelta(days=days - 1)).date()
    end_date = latest_ny.date()

    print(f"Newest bar (NY time): {latest_ny}")
    print(f"Fetching from {start_date} to {end_date} (inclusive)")

    # Loop through each day and fetch data
    current_date = start_date
    total_days = 0
    while current_date <= end_date:
        data = get_day_data(symbol, current_date)
        if data is not None and len(data) > 0:
            save_day_data(symbol, current_date, data, out_dir)
            total_days += 1
        else:
            print(f"No 1‑minute bars found for {current_date} (holiday/weekend or missing data).")
        current_date += datetime.timedelta(days=1)

    print(f"\nCompleted. Exported data for {total_days} day(s).")
    mt5.shutdown()


if __name__ == "__main__":
    main()