import sys
import asyncio


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("Usage: passivbot <command> [args...]")
        print("Commands:")
        print("  live      run live trading bot")
        print("  backtest  run backtester")
        print("  optimize  run optimizer")
        sys.exit(0 if len(sys.argv) >= 2 else 1)

    cmd = sys.argv[1]
    sys.argv = [f"passivbot {cmd}"] + sys.argv[2:]

    if cmd == "live":
        from passivbot import main as _main
        asyncio.run(_main())
    elif cmd == "backtest":
        from backtest import main as _main
        asyncio.run(_main())
    elif cmd == "optimize":
        from optimize import main as _main
        asyncio.run(_main())
    else:
        print(f"Unknown command: {cmd}")
        print("Use: passivbot live|backtest|optimize")
        sys.exit(1)
