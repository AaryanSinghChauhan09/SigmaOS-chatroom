"""LAN chat server for SigmaOS-chatroom (inspired by jargonaut).

Pure logic: a room/user registry plus deterministic message routing, all
in-memory and testable without sockets. serve-plan and broadcast-plan produce
plans; a thin socket apply layer would deliver them on a live session.
"""
import argparse, os, re, sys

ENGINE = {
    "name": "sigma-chat",
    "summary": "LAN chat server: rooms, users, broadcast routing",
    "language": "python",
    "verbs": ["serve-plan", "rooms", "users", "broadcast-plan"],
    "principles": ["Abstraction", "Separation of Concerns", "Fail-Fast",
                   "KISS", "Deterministic Testing", "Information Hiding"],
}

cli_doc = """\
$ sigma-chat serve-plan --port 6667
$ sigma-chat rooms
$ sigma-chat users
$ sigma-chat broadcast-plan --user alice --text "hello" --kind room
"""

_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,16}$")
_ROOM_RE = re.compile(r"^[A-Za-z0-9_-]{1,24}$")


class ChatError(ValueError):
    pass


class ChatServer:
    """In-memory registry. Users map to a room; rooms have a capacity."""

    def __init__(self):
        self.users = {}   # name -> {"room": None|str, "connected": bool}
        self.rooms = {}   # name -> {"capacity": int, "members": set}


def register_user(server, name):
    name = str(name).strip()
    if not _NAME_RE.match(name):
        raise ChatError(f"bad user name: {name!r} (want [A-Za-z0-9_-]{{1,16}})")
    if name in server.users:
        raise ChatError(f"user already registered: {name}")
    server.users[name] = {"room": None, "connected": True}
    return server.users[name]


def create_room(server, name, capacity=64):
    name = str(name).strip()
    if not _ROOM_RE.match(name):
        raise ChatError(f"bad room name: {name!r}")
    if name in server.rooms:
        raise ChatError(f"room already exists: {name}")
    try:
        capacity = int(capacity)
    except (TypeError, ValueError):
        raise ChatError(f"bad capacity: {capacity!r}")
    if not 1 <= capacity <= 1024:
        raise ChatError(f"capacity must be 1..1024, got {capacity}")
    server.rooms[name] = {"capacity": capacity, "members": set()}
    return server.rooms[name]


def join(server, user, room):
    """Join a room (leaving any previous one). Fail-fast on full rooms."""
    if user not in server.users:
        raise ChatError(f"unknown user: {user}")
    if room not in server.rooms:
        raise ChatError(f"unknown room: {room}")
    r = server.rooms[room]
    if user not in r["members"] and len(r["members"]) >= r["capacity"]:
        raise ChatError(f"room full: {room} (capacity {r['capacity']})")
    old = server.users[user]["room"]
    if old is not None and old != room:
        server.rooms[old]["members"].discard(user)
    r["members"].add(user)
    server.users[user]["room"] = room
    return room


def leave(server, user):
    """Leave the current room and disconnect. Fail-fast on unknown users."""
    if user not in server.users:
        raise ChatError(f"unknown user: {user}")
    room = server.users[user]["room"]
    if room is not None:
        server.rooms[room]["members"].discard(user)
    server.users[user]["room"] = None
    server.users[user]["connected"] = False
    return user


def users_in(server, room):
    if room not in server.rooms:
        raise ChatError(f"unknown room: {room}")
    return sorted(server.rooms[room]["members"])


def broadcast(server, sender, text, kind="room"):
    """Route a message. Pure: returns [(recipient, message_dict), ...] sorted.

    kind="room"   -> everyone in the sender's room except the sender
    kind="server" -> every connected user except the sender
    """
    if not str(text).strip():
        raise ChatError("empty message")
    user = server.users.get(sender)
    if user is None:
        raise ChatError(f"unknown user: {sender}")
    if not user["connected"]:
        raise ChatError(f"user not connected: {sender}")
    if kind == "room":
        room = user["room"]
        if room is None:
            raise ChatError(f"{sender} is not in a room")
        targets = [u for u in server.rooms[room]["members"] if u != sender]
    elif kind == "server":
        targets = [u for u, info in server.users.items()
                   if info["connected"] and u != sender]
    else:
        raise ChatError(f"unknown kind: {kind} (have: room, server)")
    msg = {"from": sender, "text": str(text), "kind": kind, "room": user["room"]}
    return [(t, dict(msg)) for t in sorted(targets)]


def serve_plan(server, host="0.0.0.0", port=6667):
    """Pure plan for standing up the server (no sockets are opened)."""
    host = str(host).strip()
    if not host or " " in host:
        raise ChatError(f"bad host: {host!r}")
    try:
        port = int(port)
    except (TypeError, ValueError):
        raise ChatError(f"bad port: {port!r}")
    if not 1024 <= port <= 65535:
        raise ChatError(f"port must be 1024..65535, got {port}")
    return {"host": host, "port": port, "rooms": sorted(server.rooms),
            "users": sum(1 for u in server.users.values() if u["connected"])}


def broadcast_plan(server, sender, text, kind="room"):
    """Pure dry-run of a broadcast: who would receive what."""
    deliveries = broadcast(server, sender, text, kind)
    return {"count": len(deliveries),
            "deliveries": [{"to": to, "message": msg} for to, msg in deliveries]}


def deliver(deliveries, sink=None):
    """Execute layer: hand deliveries to a transport sink (sockets in real use).

    self_test uses a list.append sink, never a real socket.
    """
    if sink is None:
        def sink(d):
            print(f"{d['to']} <= {d['message']['from']}: {d['message']['text']}")
    n = 0
    for d in deliveries:
        sink(d)
        n += 1
    return n


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=ENGINE["name"], description=ENGINE["summary"])
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("serve-plan", help="plan the listener (no sockets)")
    sp.add_argument("--host", default="0.0.0.0")
    sp.add_argument("--port", type=int, default=6667)
    rm = sub.add_parser("rooms", help="list rooms and member counts")
    rm.add_argument("--demo", action="store_true",
                    help="seed a demo room/user graph for illustration")
    us = sub.add_parser("users", help="list users and their room")
    us.add_argument("--demo", action="store_true")
    bp = sub.add_parser("broadcast-plan", help="dry-run message routing")
    bp.add_argument("--user", required=True)
    bp.add_argument("--text", required=True)
    bp.add_argument("--kind", choices=("room", "server"), default="room")
    bp.add_argument("--demo", action="store_true")
    return p


def _demo_server():
    """Deterministic demo graph used by the --demo illustration flag."""
    srv = ChatServer()
    create_room(srv, "general")
    create_room(srv, "dev", capacity=2)
    for u in ("alice", "bob", "carol"):
        register_user(srv, u)
    join(srv, "alice", "general")
    join(srv, "bob", "general")
    join(srv, "carol", "dev")
    return srv


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "serve-plan":
            plan = serve_plan(host=args.host, port=args.port)
            print(f"listen {plan['host']}:{plan['port']} "
                  f"rooms={','.join(plan['rooms']) or '-'} users={plan['users']}")
            return 0
        srv = _demo_server() if args.demo else ChatServer()
        if args.cmd == "rooms":
            for name in sorted(srv.rooms):
                print(f"{name}\t{len(srv.rooms[name]['members'])}")
        elif args.cmd == "users":
            for name in sorted(srv.users):
                info = srv.users[name]
                print(f"{name}\troom={info['room'] or '-'}"
                      f"\t{'connected' if info['connected'] else 'gone'}")
        elif args.cmd == "broadcast-plan":
            plan = broadcast_plan(srv, args.user, args.text, kind=args.kind)
            for d in plan["deliveries"]:
                print(f"{d['to']} <= {d['message']['from']}: {d['message']['text']}")
            print(f"recipients={plan['count']}")
        return 0
    except (ChatError, OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def self_test() -> None:
    srv = ChatServer()
    create_room(srv, "general")
    create_room(srv, "dev", capacity=2)
    for u in ("alice", "bob", "carol", "dave"):
        register_user(srv, u)
    join(srv, "alice", "general")
    join(srv, "bob", "general")
    join(srv, "carol", "dev")
    assert users_in(srv, "general") == ["alice", "bob"]
    # room routing: sender excluded, members sorted, message cloned per target
    d = broadcast(srv, "alice", "hello")
    assert [t for t, _ in d] == ["bob"]
    assert d[0][1] == {"from": "alice", "text": "hello", "kind": "room",
                       "room": "general"}
    # fail-fast: sender not in a room
    try:
        broadcast(srv, "dave", "anyone?")
    except ChatError:
        pass
    else:
        raise AssertionError("broadcast outside a room not caught")
    # moving rooms removes from the old room
    join(srv, "alice", "dev")
    assert users_in(srv, "general") == ["bob"]
    assert users_in(srv, "dev") == ["alice", "carol"]
    # capacity enforcement (dev capacity=2, now full)
    try:
        join(srv, "dave", "dev")
    except ChatError:
        pass
    else:
        raise AssertionError("full room not enforced")
    # server-wide routing: connected users except sender, sorted
    g = broadcast(srv, "carol", "hi all", kind="server")
    assert [t for t, _ in g] == ["alice", "bob", "dave"]
    # leaving disconnects and drops room membership
    leave(srv, "bob")
    assert users_in(srv, "general") == []
    assert srv.users["bob"]["connected"] is False
    try:
        broadcast(srv, "bob", "ghost")
    except ChatError:
        pass
    else:
        raise AssertionError("broadcast from disconnected user not caught")
    # plan builders (pure, no sockets anywhere)
    plan = serve_plan(srv, host="127.0.0.1", port=7777)
    assert plan == {"host": "127.0.0.1", "port": 7777, "rooms": ["dev", "general"],
                    "users": 3}   # alice, carol, dave still connected
    for bad in (lambda: serve_plan(srv, port=80),
                lambda: serve_plan(srv, host="bad host"),
                lambda: serve_plan(srv, port="x")):
        try:
            bad()
        except ChatError:
            pass
        else:
            raise AssertionError("expected ChatError for bad serve plan")
    bp = broadcast_plan(srv, "alice", "hey")
    assert bp["count"] == 1 and bp["deliveries"][0]["to"] == "carol"
    # deliver uses an injected (recording) sink, never a real socket
    seen = []
    assert deliver(bp["deliveries"], sink=seen.append) == 1
    assert seen == bp["deliveries"]
    # fail-fast input validation
    for bad in (lambda: register_user(srv, "bad name"),
                lambda: register_user(srv, "alice"),
                lambda: create_room(srv, "bad room"),
                lambda: create_room(srv, "new", capacity=0),
                lambda: join(srv, "alice", "ghost"),
                lambda: join(srv, "ghost", "dev"),
                lambda: broadcast(srv, "alice", "   "),
                lambda: broadcast(srv, "alice", "x", kind="dm")):
        try:
            bad()
        except ChatError:
            pass
        else:
            raise AssertionError("expected ChatError")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
