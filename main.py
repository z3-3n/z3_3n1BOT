# BLACK HEART launcher
from black_heart import tg
import black_heart_developers  # Register persistent developer command bridge
import black_heart_profile  # Profile, photos, aligned ASCII art and fun commands

if __name__ == "__main__":
    print("🖤 BLACK HEART starting...")
    tg.start()
    tg.run_until_disconnected()
