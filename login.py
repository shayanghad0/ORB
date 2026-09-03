import MetaTrader5 as mt5
import sys

# ----------------------------------------------------------------------
# Function to login to MT5 account
# ----------------------------------------------------------------------
def login_mt5(login, password, server=None):
    """
    Initialize MT5 connection and login to account.
    :param login: Account number (int or str)
    :param password: Account password (str)
    :param server: Trade server name (str), optional
    :return: True if successful, False otherwise
    """
    # Initialize MT5 connection (if not already initialized)
    if not mt5.initialize():
        print("MT5 initialization failed, error code =", mt5.last_error())
        return False

    # Prepare login parameters
    login_dict = {
        "login": int(login),      # Account number must be integer
        "password": password,
    }
    if server:
        login_dict["server"] = server

    # Attempt login
    print(f"Logging in to account {login} ...")
    authorized = mt5.login(**login_dict)
    if authorized:
        account_info = mt5.account_info()
        if account_info is not None:
            print("Login successful!")
            print(f"Account: {account_info.login}")
            print(f"Server:  {account_info.server}")
            print(f"Balance: {account_info.balance}")
            print(f"Currency:{account_info.currency}")
            return True
        else:
            print("Login succeeded but failed to retrieve account info.")
            return False
    else:
        print("Login failed. Error code:", mt5.last_error())
        return False

# ----------------------------------------------------------------------
# Main - get credentials from user
# ----------------------------------------------------------------------
if __name__ == "__main__":
    login = input("Enter account login (number): ").strip()
    password = input("Enter account password: ").strip()
    server = input("Enter server name (optional, press Enter to skip): ").strip()

    # Remove quotes if user pasted password with quotes
    if password.startswith('"') and password.endswith('"'):
        password = password[1:-1]
    if server.startswith('"') and server.endswith('"'):
        server = server[1:-1]

    success = login_mt5(login, password, server if server else None)

    if success:
        # Keep connection open, do something...
        # For example, get account info again
        info = mt5.account_info()
        print("\nAccount details:")
        print(f"Name: {info.name}")
        print(f"Leverage: 1:{info.leverage}")
        print(f"Margin mode: {'Hedging' if info.margin_mode == mt5.ACCOUNT_MARGIN_MODE_RETAIL_HEDGING else 'Netting'}")
        print(f"Trade allowed: {'Yes' if info.trade_allowed else 'No'}")
        print(f"Expert advisor allowed: {'Yes' if info.trade_expert else 'No'}")
    else:
        print("\nLogin failed. Check your credentials and server name.")
        # Optionally show available servers? Not easily possible without terminal connection.

    # Shutdown MT5 connection
    mt5.shutdown()