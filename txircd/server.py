# -*- coding: utf-8 -*-

from txircd.utils import irc_lower

class IRCServer:
    def __init__(self, parent, server, password):
        assert server[0] not in parent.factory.servers, "Server already known"
        assert server[1] == "0", "Server isn't a local peer"
        assert password[1][:4] == "0210", "Invalid password version"
        assert password[2].find("|") != -1, "Invalid password flags"
        # TODO: check password
        self.parent = parent
        self.name = server[0]
        parent.factory.servers[server[0]] = {
            "name": server[0],
            "description": server[3],
            "token": server[2],
            "host": parent.transport.getHandle().getpeername()[0],
            "socket": parent,
            "hops": 0
        }
        # More connection logic here
        self.parent.sendLine("PASS %s %s %s" % (parent.factory.password, "0210", "|"))
        self.parent.sendLine("SERVER %s %d %s :%s" % (parent.factory.name, 0, parent.factory.token, parent.factory.description))
        for s in parent.factory.servers.itervalues():
            self.parent.sendLine("SERVER %s %d %s :%s" % (s.name, s.hops+1, s.token, s.description))
        for u in parent.factory.users.itervalues():
            s = parent.factory.servers[u.server]
            if u.service:
                self.parent.sendLine("SERVICE %s %s %s %s %d :%s" % (u.nickname, s.token, "*", "", s.hops+1, u.realname))
            else:
                self.parent.sendLine("NICK %s %d %s %s %s %s :%s" % (u.nickname, s.hops+1, u.username, u.hostname, s.token, u.mode, u.realname))
        for c in parent.factory.channels.itervalues():
            users = []
            for name, mode in c.users.iteritems():
                u = ""
                if mode.find("O") != -1:
                    u = "@@"
                elif mode.find("o") != -1:
                    u = "@"
                if mode.find("v") != -1:
                    u += "+"
                u += name
                users.append(u)
            self.parent.sendline("NJOIN %s :%s" % (c.name, ",".join(users)))

    def relay(self, message):
        for s in self.parent.factory.servers.itervalues():
            if s.socket != self.parent and s.hops == 0:
                s.socket.sendLine(message)

    def irc_NICK(self, prefix, params):
        assert params[0] not in self.parent.factory.users, "Nickname in use"
        self.relay("NICK %s %d %s %s %s %s :%s" % (params[0], int(params[1])+1, params[2], params[3], params[4], params[5], params[6]))
        for s in self.parent.factory.servers.itervalues():
            if s.token == params[4]:
                self.parent.factory.users[params[0]] = {
                    "socket": self.parent,
                    "nickname": params[0],
                    "username": params[2],
                    "realname": params[6],
                    "hostname": params[3],
                    "server": s.name,
                    "oper": False,
                    "signon": time.time(),
                    "lastactivity": time.time(),
                    "away": False,
                    "mode": params[5],
                    "channels": [],
                    "service": False
                }

    def irc_SERVICE(self, prefix, params):
        assert params[0] not in self.parent.factory.users, "Nickname in use"
        self.relay("SERVICE %s %s %s %s %d :%s" % (params[0], s.token, params[2], params[3], int(params[4])+1, params[5]))
        for s in self.parent.factory.servers.itervalues():
            if s.token == params[1]:
                self.parent.factory.users[params[0]] = {
                    "socket": self.parent,
                    "nickname": params[0],
                    "username": params[0],
                    "realname": params[5],
                    "hostname": params[0],
                    "server": s.name,
                    "oper": False,
                    "signon": time.time(),
                    "lastactivity": time.time(),
                    "away": False,
                    "mode": "",
                    "channels": [],
                    "service": True
                }
                

    def irc_SERVER(self, prefix, params):
        assert params[0] not in self.parent.factory.servers, "Server already connected"
        self.relay(":%s SERVER %s %s %s :%s" % (prefix, params[0], int(params[1])+1, params[2], params[3])
        self.parent.factory.servers[params[0]] = {
            "name": params[0],
            "description": params[3],
            "token": params[2],
            "host": self.parent.transport.getHandle().getpeername()[0],
            "socket": self.parent,
            "hops": int(params[1])
        }

    def irc_QUIT(self, prefix, params):
        assert prefix in self.parent.factory.users, "Nickname does not exist"
        self.relay(":%s QUIT :%s" % (prefix, params[0]))
        for c in self.parent.factory.users[prefix].channels:
            self.parent.factory.channels[c].remove(prefix)
        del self.parent.factory.users[prefix]

    def irc_SQUIT(self, prefix, params):
        if irc_lower(prefix) == irc_lower(self.parent.factory.name):
            prefix = self.name
        assert prefix in self.parent.factory.servers, "Server does not exist"
        # Broadcast message to other connected servers
        self.relay(":%s SQUIT %s :%s" % (prefix, params[0], params[1]))
        # Delete users connected through quitting server from state database
        for u in self.parent.factory.users.values():
            if u.socket == self.parent.factory.servers[prefix].socket:
                for c in u.channels:
                    self.parent.factory.broadcast(c, ":%s QUIT :%s %s" % (u.name, self.name, u.server))
                    del self.parent.factory.channels[c].users[u.name]
                del self.parent.factory.users[u.name]
        # Delete server (and other servers behind it) from state database
        for s in self.parent.factory.servers.values():
            if s.socket == self.parent.factory.servers[prefix].socket:
                del self.parent.factory.servers[s.name]

    def irc_JOIN(self, prefix, params):
        assert prefix in self.parent.factory.users, "Nickname does not exist"
        self.relay(":%s JOIN :%s" % (prefix, params[0]))
        channels = params[0].split(",")
        for c in channels:
            tmp = c.split(chr(7))
            name = tmp[0]
            mode = tmp[1] if len(tmp) > 1 else ""
            self.parent.factory.channels[name].users[prefix] = mode
            self.parent.factory.users[prefix].channels.append(name)

    def irc_NJOIN(self, prefix, params):
        self.relay(":%s NJOIN %s :%s" % (prefix, params[0], params[1]))
        channel = self.parent.factory.channels[params[1]]
        users = params[1].split(",")
        for u in users:
            mode = ""
            if u[:2] == "@@":
                mode += "O"
                u = u[2:]
            if u[:1] == "@":
                mode += "o"
                u = u[1:]
            if u[:1] == "+":
                mode += "v"
                u = u[1:]
            channel.users[u] = mode
            self.parent.factory.users[u].channels.append(params[1])

    def irc_MODE(self, prefix, params):
        assert params[0] in self.parent.factory.channels or params[0] in self.parent.factory.users, "Invalid target"
        target = params.pop(0)
        if target in self.parent.factory.channels:
            while params:
                modes = params.pop(0)
                type = modes[0]
                modes = modes[1:]
                assert type == "+" or type == "-", "Invalid mode type"
                if type == "+":
                    for mode in modes:
                        if mode in "Oov":
                            user = params.pop(0)
                            self.parent.factory.channels[target].users[user].mode += mode
                        elif mode == "k":
                            self.parent.factory.channels[target].password = params.pop(0)
                        elif mode == "l":
                            self.parent.factory.channels[target].limit = int(params.pop(0))
                        elif mode == "b":
                            self.parent.factory.channels[target].bans.append(params.pop(0))
                        elif mode == "e":
                            self.parent.factory.channels[target].exemptions.append(params.pop(0))
                        elif mode == "I":
                            self.parent.factory.channels[target].invites.append(params.pop(0))
                        else:
                            self.parent.factory.channels[target].mode += mode
                else:
                    for mode in modes:
                        if mode in "Oov":
                            user = params.pop(0)
                            self.parent.factory.channels[target].users[user].mode.replace(mode,"")
                        elif mode == "k":
                            self.parent.factory.channels[target].password = None
                        elif mode == "l":
                            self.parent.factory.channels[target].limit = None
                        elif mode == "b":
                            self.parent.factory.channels[target].bans.remove(params.pop(0))
                        elif mode == "e":
                            self.parent.factory.channels[target].exemptions.remove(params.pop(0))
                        elif mode == "I":
                            self.parent.factory.channels[target].invites.remove(params.pop(0))
                        else:
                            self.parent.factory.channels[target].mode.replace(mode,"")
        else:
            while params:
                modes = params.pop(0)
                type = modes[0]
                modes = modes[1:]
                assert type == "+" or type == "-", "Invalid mode type"
                if type == "+":
                    for mode in modes:
                        if mode in "Ooa" or mode in self.parent.factory.users[target].mode:
                            continue
                        self.parent.factory.users[target].mode += mode
                else:
                    for mode in modes:
                        if mode in "ar" or mode not in self.parent.factory.users[target].mode:
                            continue
                        self.parent.factory.users[target].mode.replace(mode, "")

    def irc_unknown(self, prefix, command, params):
        raise NotImplementedError(command, prefix, params)