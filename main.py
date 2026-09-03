import MetaTrader5 as mt5
import datetime
import pytz
import json

# New York time zone
NY_TZ = pytz.timezone('America/New_York')


def get_latest_bar_time(symbol):
    """Return the UTC datetime of the most recent 1‑minute bar for the given symbol."""
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 1)
    if rates is None or len(rates) == 0:
        return None
    # rates[0][0] is the bar's open time in seconds since epoch (UTC)
    return datetime.datetime.fromtimestamp(int(rates[0][0]), tz=pytz.UTC)


def get_day_data(symbol, target_date_ny):
    """
    Fetch 1‑minute OHLCV data for the entire day (midnight to midnight) in New York time.
    target_date_ny is a datetime.date object in the NY time zone.
    Returns a list of dictionaries, each representing one bar with time in NY time.
    """
    # Build start and end datetimes in NY time zone
    start_ny = NY_TZ.localize(
        datetime.datetime(target_date_ny.year, target_date_ny.month, target_date_ny.day, 0, 0, 0)
    )
    end_ny = NY_TZ.localize(
        datetime.datetime(target_date_ny.year, target_date_ny.month, target_date_ny.day, 23, 59, 59)
    )
    # Convert to UTC for MetaTrader5
    start_utc = start_ny.astimezone(pytz.UTC)
    end_utc = end_ny.astimezone(pytz.UTC)

    rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M1, start_utc, end_utc)
    if rates is None:
        return None

    data = []
    for rate in rates:
        # rate[0] is UTC timestamp (integer seconds)
        dt_utc = datetime.datetime.fromtimestamp(int(rate[0]), tz=pytz.UTC)
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


def main():
    # Initialize MetaTrader 5
    if not mt5.initialize():
        print("MT5 initialization failed.")
        return
    print("MT5 initialized successfully.")

    # Ask user for symbol
    symbol = input("Enter symbol (e.g., XAUUSD): ").strip().upper()
    if not mt5.symbol_info(symbol):
        print(f"Symbol '{symbol}' not found.")
        mt5.shutdown()
        return
    mt5.symbol_select(symbol, True)

    # Ask for number of days to go back
    days_str = input("Enter number of days (e.g., 2): ")
    try:
        days = int(days_str)
    except ValueError:
        print("Invalid input. Please enter an integer.")
        mt5.shutdown()
        return

    # Get the newest available bar time
    latest_utc = get_latest_bar_time(symbol)
    if latest_utc is None:
        print(f"No data available for {symbol}.")
        mt5.shutdown()
        return

    # Convert latest bar time to New York time and compute target date
    latest_ny = latest_utc.astimezone(NY_TZ)
    target_date = (latest_ny - datetime.timedelta(days=days)).date()

    print(f"Newest bar (NY time): {latest_ny}")
    print(f"Target date (NY): {target_date}")

    # Fetch data for the target day
    data = get_day_data(symbol, target_date)
    if data is None:
        print(f"No data retrieved for {target_date}.")
    elif len(data) == 0:
        print(f"No 1‑minute bars found for {target_date} (maybe a holiday/weekend).")
    else:
        # Save to JSON file
        filename = f"{symbol}_{target_date.isoformat()}_M1.json"
        with open(filename, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"Saved {len(data)} bars to '{filename}'.")

    mt5.shutdown()


if __name__ == "__main__":
    main()