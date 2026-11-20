"""opennotch            -> run the notch
opennotch say TEXT [--icon ok|fail|info] [--seconds N]  -> pop a message out of the running notch"""
import argparse
import sys

from . import protocol, socket_path


def main(argv=None):
    ap = argparse.ArgumentParser(prog="opennotch", description="A Dynamic-Island-style notch for Linux.")
    sub = ap.add_subparsers(dest="cmd")
    for command, description, icon in (("say", "show a message", "info"),
                                       ("done", "show an agent completion notice", "ok")):
        notice = sub.add_parser(command, help=description)
        notice.add_argument("text")
        notice.add_argument("--icon", choices=protocol.ICONS, default=icon)
        notice.add_argument("--seconds", type=float, default=5)
    sub.add_parser("screenshot", help="save a screenshot of the current screen")
    sub.add_parser("record", help="start or stop recording the current screen")
    sub.add_parser("settings", help="open the Settings window")
    args = ap.parse_args(argv)
    if args.cmd == "settings":
        from .settings import main as settings_main
        return settings_main()

    if args.cmd in ("say", "done", "screenshot", "record"):
        request = {"cmd": args.cmd}
        if args.cmd in ("say", "done"):
            request.update(text=args.text, icon=args.icon, seconds=args.seconds)
        try:
            reply = protocol.request(socket_path(), request)
        except OSError:
            print("opennotch: the notch is not running (start it with `opennotch`)", file=sys.stderr)
            return 2
        if not reply.get("ok"):
            print("opennotch:", reply.get("error"), file=sys.stderr)
            return 1
        return 0

    from .app import main as run
    return run()


if __name__ == "__main__":
    sys.exit(main())
