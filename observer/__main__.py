"""TOWN_OBSERVER_DEMO=1 python3 -m observer  → 带演示人口的观测站。"""

from world.http_app import main

if __name__ == "__main__":
    import os
    os.environ.setdefault("TOWN_OBSERVER_DEMO", "1")
    main()
