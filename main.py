# BLACK HEART launcher
from black_heart import tg
import black_heart_trigger  # Register incoming 'اسود' keyword reply

if __name__ == "__main__":
    print("🖤 BLACK HEART starting...")
    tg.start()
    tg.run_until_disconnected()
