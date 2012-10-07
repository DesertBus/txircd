# -*- coding: utf-8 -*-

from twisted.internet import reactor
from twisted.python import log
from twisted.words.protocols import irc
from txircd.user import IRCUser
from txircd.utils import irc_lower, chunk_message, now
from pbkdf2 import crypt
import inspect, random

NICKSERV_HELP_MESSAGE = """
\x02NickServ\x0F matches your IRC nickname to your Donor account, allowing for a painless 
auction process, as well as the peace of mind that nobody can use your nickname but you. 
To use a command, type \x02/msg NickServ \x1Fcommand\x0F. For more information on a command, type 
\x02/msg NickServ HELP \x1Fcommand\x0F.
""".replace("\n","")

def _register_donor_account(txn, nickname, email, password, username, qmark):
    query = "INSERT INTO donors(email, password, display_name) VALUES({0},{0},{0})".format(qmark)
    txn.execute(query, (email, password, username))
    id = txn.lastrowid
    query = "INSERT INTO irc_nicks(donor_id, nick) VALUES({0},{0})".format(qmark)
    txn.execute(query, (id, nickname))
    return id
    
class DBUser(IRCUser):
    services = ["nickserv","bidserv"]

    # Start the party off right
    def __init__(self, parent, user, password, nick):
        # Service nicks are technically valid and not in use, but you can't have them.
        if irc_lower(nick) in self.services:
            parent.sendMessage(irc.ERR_NICKNAMEINUSE, nick, ":Nickname is already in use", prefix=parent.factory.hostname)
            parent.sendMessage("ERROR",":Closing Link: {}".format(nick))
            parent.transport.loseConnection()
            raise ValueError("Invalid nickname")
        IRCUser.__init__(self, parent, user, password, nick)
        self.auth_timer = None
        self.nickserv_id = None
        if password:
            if ":" in password:
                username, chaff, password = password.partition(":")
                print("AUTH", username, password)
                self.auth(username, password)
            else:
                print("TOKEN", password)
                self.token(password)
        else:
            self.checkNick()
    
    # Called when they occur
    def registered(self):
        for channel in self.channels.iterkeys():
            c = self.ircd.channels[channel]
            m, b, f = c.mode.combine("+v",[self.nickname],c.name)
            if m: # Should always be true!?
                c.log.write("[{:02d}:{:02d}:{:02d}] {} set modes {}\n".format(now().hour, now().minute, now().second, "BidServ", m))
                for u in c.users.itervalues():
                    u.socket.sendMessage("MODE", c.name, m, prefix=self.ircd.hostname)
    
    def unregistered(self):
        for channel in self.channels.iterkeys():
            c = self.ircd.channels[channel]
            m, b, f = c.mode.combine("-v",[self.nickname],c.name)
            if m: # Should always be true!?
                c.log.write("[{:02d}:{:02d}:{:02d}] {} set modes {}\n".format(now().hour, now().minute, now().second, "BidServ", m))
                for u in c.users.itervalues():
                    u.socket.sendMessage("MODE", c.name, m, prefix=self.ircd.hostname)
    
    # Restrict what people in the "need to identify" phase can do
    def handleCommand(self, command, prefix, params):
        # If we aren't waiting for auth, let them do as they please
        if self.auth_timer is None:
            IRCUser.handleCommand(self, command, prefix, params)
        # Allow some basic command, plus PRIVMSG so they can identify
        elif command in ["PING","PONG","NICK","PRIVMSG","QUIT","NS","NICKSERV"]:
            IRCUser.handleCommand(self, command, prefix, params)
        else:
            self.socket.sendMessage("NOTICE", self.nickname, ":You can not use command \x02{}\x0F while identifying a registered nick.".format(command), prefix=self.ircd.hostname)
    
    # Aliases to make life easier on people
    def irc_NS(self, prefix, params):
        message = " ".join(params)
        self.irc_PRIVMSG(prefix, ["NickServ", message])
    
    def irc_NICKSERV(self, prefix, params):
        message = " ".join(params)
        self.irc_PRIVMSG(prefix, ["NickServ", message])
    
    def irc_BID(self, prefix, params):
        message = " ".join(["BID"] + params)
        self.irc_PRIVMSG(prefix, ["BidServ", message])
    
    # Voice registered users when they enter the room
    def join(self, channel, key):
        IRCUser.join(self, channel, key)
        if channel in self.channels and self.nickserv_id:
            c = self.ircd.channels[channel]
            m, b, f = c.mode.combine("+v",[self.nickname],c.name)
            if m: # Should always be true!?
                c.log.write("[{:02d}:{:02d}:{:02d}] {} set modes {}\n".format(now().hour, now().minute, now().second, "BidServ", m))
                for u in c.users.itervalues():
                    u.socket.sendMessage("MODE", c.name, m, prefix=self.ircd.hostname)
    
    # Track nick changes
    def irc_NICK(self, prefix, params):
        if params and irc_lower(params[0]) in self.services: # Can't use a service nick
            self.socket.sendMessage(irc.ERR_NICKNAMEINUSE, params[0], ":Nickname is already in use", prefix=self.ircd.hostname)
            return
        oldnick = irc_lower(self.nickname)
        IRCUser.irc_NICK(self, prefix, params)
        newnick = irc_lower(self.nickname)
        if oldnick != newnick:
            self.checkNick()
    
    # Delegate PRIVMSG to handlers
    def irc_PRIVMSG(self, prefix, params):
        # You can only PRIVMSG NickServ while identifying
        if params and self.auth_timer is not None and irc_lower(params[0]) != "nickserv":
            self.socket.sendMessage("NOTICE", self.nickname, ":You can not PRIVMSG anybody but NickServ while identifying a registered nick.".format(command), prefix=self.ircd.hostname)
            return
        if len(params) > 1 and irc_lower(params[0]) in self.services:
            service = irc_lower(params[0])
            command, chaff, params = params[1].partition(" ")
            params = filter(lambda x: x, params.split(" "))
            method = getattr(self, "{}_{}".format(service, command.upper()), None)
            if method is None:
                method = getattr(self, "{}_USAGE".format(service), None)
                method(prefix, params, command)
            else:
                method(prefix, params)
        else:
            IRCUser.irc_PRIVMSG(self, prefix, params)
    
    # =========================
    # === NICKSERV HANDLERS ===
    # =========================
    
    # We'll be needing these quite a bit
    def query(self, query, *args):
        query = query.format(self.ircd.db_marker)
        return self.ircd.db.runQuery(query, args)
    
    def failedAuth(self, result, reason):
        self.socket.sendMessage("NOTICE", self.nickname, ":Failed Authorization [{}]".format(reason), prefix=self.ircd.hostname)
    
    def ohshit(self, result):
        log.msg("Shit!!!!")
        self.irc_QUIT(None, ["Catastrophic System Failure"])
        return result
    
    def genNick(self):
        nick = "{}{:>06d}".format(self.ircd.nickserv_guest_prefix, random.randrange(1000000))
        if nick in self.ircd.users:
            return self.genNick()
        return nick
    
    # Phase 1
    def auth(self, username, password):
        d = self.query("SELECT id, password, display_name FROM donors WHERE email = {0}", username)
        d.addCallback(self.verifyPassword, password)
        d.addErrback(self.failedAuth, "Internal Server Error")
        return d
    
    def token(self, password):
        d = self.query("SELECT donor_id FROM irc_tokens WHERE token = {0}", password)
        d.addCallback(self.loadDonorInfo)
        d.addErrback(self.failedAuth, "Internal Server Error")
        return d
    
    def checkNick(self):
        if self.auth_timer:
            self.auth_timer.cancel()
            self.auth_timer = None
        nickname = irc_lower(self.nickname)
        d = self.query("SELECT donor_id FROM irc_nicks WHERE nick = {0}", nickname)
        d.addCallback(self.beginVerify, nickname)
        d.addErrback(self.ohshit)
        return d
    
    # Phase 2
    def verifyPassword(self, result, password):
        if not result:
            self.checkNick()
            self.failedAuth(None, "Invalid Email or Password")
            return
        hash = result[0][1] # Is there a better way?? Named parameters??
        check = crypt(password, hash)
        if check == hash:
            self.nickserv_id = result[0][0]
            self.account = result[0][2]
            if self.auth_timer:
                self.auth_timer.cancel()
                self.auth_timer = None
            self.socket.sendMessage("NOTICE", self.nickname, ":You are now identified. Welcome, {}.".format(self.account), prefix=self.ircd.hostname)
            self.checkNick()
            self.registered()
        else:
            self.checkNick()
            self.failedAuth(None, "Invalid Email or Password")
    
    def loadDonorInfo(self, result):
        if not result:
            self.checkNick()
            self.failedAuth(None, "Invalid Auth Token")
            return
        d = self.query("SELECT id, display_name FROM donors WHERE id = {0}", result[0][0])
        d.addCallback(self.setDonorInfo)
        d.addErrback(self.failedAuth, "Internal Server Error")
        return d
    
    def beginVerify(self, result, nickname):
        if nickname != irc_lower(self.nickname):
            return # Changed nick too fast, don't even worry about it
        elif result:
            id = result[0][0]
            if self.nickserv_id and self.nickserv_id == id:
                if self.auth_timer: # Clear the timer
                    self.auth_timer.cancel()
                    self.auth_timer = None
                return # Already identified
            self.socket.sendMessage("NOTICE", self.nickname, ":This is a registered nick. Please use \x02/msg nickserv login EMAIL PASSWORD\x0F to verify your identity", prefix=self.ircd.hostname)
            if self.auth_timer:
                self.auth_timer.cancel() # In case we had another going
            self.auth_timer = reactor.callLater(self.ircd.nickserv_timeout, self.changeNick, id, nickname)
        elif self.nickserv_id:
            # Try to register the nick
            d = self.query("SELECT nick FROM irc_nicks WHERE donor_id = {0}", self.nickserv_id)
            d.addCallback(self.registerNick, nickname)
            d.addErrback(self.failedRegisterNick, nickname)
    
    # Phase 3
    def setDonorInfo(self, result):
        if not result:
            self.checkNick()
            self.failedAuth(None, "Internal Server Error")
            return
        self.nickserv_id = result[0][0]
        self.account = result[0][1]
        if self.auth_timer:
            self.auth_timer.cancel()
            self.auth_timer = None
        self.socket.sendMessage("NOTICE", self.nickname, ":You are now identified. Welcome, {}.".format(self.account), prefix=self.ircd.hostname)
        self.checkNick()
        self.registered()
    
    def changeNick(self, id, nickname):
        self.auth_timer = None
        if self.nickserv_id == id:
            return # Somehow we auth'd and didn't clear the timer?
        if irc_lower(self.nickname) != nickname:
            return # Changed nick before the timeout. Whatever
        self.irc_NICK(None, [self.genNick()])
    
    def registerNick(self, result, nickname):
        if len(result) >= self.ircd.nickserv_limit:
            # Already registered all the nicks we can
            nicklist = ", ".join([l[0] for l in result[:-2]])+", or "+result[-1][0] if len(result) > 1 else result[0][0]
            message = ":Warning: You already have {!s} registered nicks, so {} will not be protected. Please switch to {} to prevent impersonation!".format(self.ircd.nickserv_limit, nickname, nicklist)
            self.socket.sendMessage("NOTICE", self.nickname, message, prefix=self.ircd.hostname)
        else:
            d = self.query("INSERT INTO irc_nicks(donor_id, nick) VALUES({0},{0})", self.nickserv_id, nickname)
            d.addCallback(self.successRegisterNick, nickname)
            d.addErrback(self.failedRegisterNick, nickname)
    
    def failedRegisterNick(self, result, nickname):
        self.socket.sendMessage("NOTICE", self.nickname, ":Failed to register nick {} to account {}. Other users may still use it.".format(nickname, self.account), prefix=self.ircd.hostname)
    
    # Phase 4
    def successRegisterNick(self, result, nickname):
        self.socket.sendMessage("NOTICE", self.nickname, ":Nickname {} is now registered to account {} and can not be used by any other user.".format(nickname, self.account), prefix=self.ircd.hostname)
    
    # =========================
    # === NICKSERV COMMANDS ===
    # =========================
    
    def nickserv_USAGE(self, prefix, params, command = None):
        if command:
            self.socket.sendMessage("NOTICE", self.nickname, ":Unknown command \x02{}\x0F. \"/msg NickServ HELP\" for help.".format(command), prefix=self.ircd.hostname)
        else:
            self.socket.sendMessage("NOTICE", self.nickname, ":Usage: /msg NickServ COMMAND [OPTIONS] -- Use /msg NickServ HELP for help", prefix=self.ircd.hostname)
    
    def nickserv_HELP(self, prefix, params):
        log.msg(repr(params))
        if not params:
            # Get all available commands
            methods = filter(lambda x: x[0].startswith("nickserv_"), inspect.getmembers(self, inspect.ismethod))
            # Prepare the format string to make everything nice
            fmtstr = "    {{:<{!s}}} {{}}"
            name_length = max([len(m[0]) for m in methods]) - 9
            fmtstr = fmtstr.format(name_length)
            # Include the header
            lines = chunk_message(NICKSERV_HELP_MESSAGE, self.ircd.motd_line_length)
            lines.append("")
            # Add the commands and make them pretty
            for m in methods:
                if m[0] == "nickserv_USAGE" or m[0] == "nickserv_HELP":
                    continue
                doc = inspect.getdoc(m[1])
                lines.append(fmtstr.format(m[0][9:], doc.splitlines()[0]))
            # Now dump all that text to the user
            for l in lines:
                self.socket.sendMessage("NOTICE", self.nickname, ":{}".format(l), prefix=self.ircd.hostname)
        else:
            # Try to load the command
            func = getattr(self, "nickserv_{}".format(params[0].upper()), None)
            if not func: # Doesn't exist :(
                self.socket.sendMessage("NOTICE", self.nickname, ":Unknown command \x02{}\x0F. \"/msg NickServ HELP\" for help.".format(params[0]), prefix=self.ircd.hostname)
            else:
                doc = inspect.getdoc(func)
                lines = doc.splitlines()[1:] # Cut out the short help message
                for l in lines: # Print the long message
                    self.socket.sendMessage("NOTICE", self.nickname, ":{}".format(l), prefix=self.ircd.hostname)
        
    def nickserv_REGISTER(self, prefix, params):
        """Create a donor account via IRC
        Syntax: \x02REGISTER \x1Fpassword\x1F \x1Femail\x1F \x1F[name]\x0F
        
        Creates a donor account with the specified email and password.
        Your current nick will be immediately associated with the new
        account and protected from impersonation. You'll also be voiced
        and allowed to bid in all auctions."""
        if len(params) < 2:
            self.socket.sendMessage("NOTICE", self.nickname, ":Syntax: \x02REGISTER \x1Fpassword\x1F \x1Femail \x1F[name]\x0F", prefix=self.ircd.hostname)
            return
        email = params[1]
        password = crypt(params[0])
        name = " ".join(params[2:]) if len(params) > 2 else "Anonymous"
        d = self.ircd.db.runInteraction(_register_donor_account, self.nickname, email, password, name, self.ircd.db_marker)
        d.addCallback(self.ns_registered, email, name)
        d.addErrback(self.ns_notregistered, email, name)
    
    def nickserv_IDENTIFY(self, prefix, params):
        """Backwards compatible version of LOGIN
        Syntax: \x02IDENTIFY \x1Femail\x1F:\x1Fpassword\x0F
        
        Logs in to a donor account with the specified email and password.
        If it isn't already, your current nick will be associated with the
        account and protected from impersonation. You'll also be voiced
        and allowed to bid in all auctions."""
        if not params or params[0].find(":") < 0:
            self.socket.sendMessage("NOTICE", self.nickname, ":Syntax: \x02IDENTIFY \x1Femail\x1F:\x1Fpassword\x0F", prefix=self.ircd.hostname)
            return
        email, chaff, password = params[0].partition(":")
        self.auth(email, password)
    
    def nickserv_LOGIN(self, prefix, params):
        """Log in to an existing Donor account
        Syntax: \x02LOGIN \x1Femail\x1F \x1Fpassword\x0F
        
        Logs in to a donor account with the specified email and password.
        If it isn't already, your current nick will be associated with the
        account and protected from impersonation. You'll also be voiced
        and allowed to bid in all auctions."""
        if len(params) < 2:
            self.socket.sendMessage("NOTICE", self.nickname, ":Syntax: \x02LOGIN \x1Femail\x1F \x1Fpassword\x0F", prefix=self.ircd.hostname)
            return
        self.auth(params[0], params[1])
    
    def nickserv_LOGOUT(self, prefix, params):
        """Log out of your donor account
        Syntax: \x02LOGOUT\x0F
        
        Logs out of whatever account you are in right now. Useful to
        prevent your roommate from bidding on auctions in your name."""
        if not self.account:
            self.socket.sendMessage("NOTICE", self.nickname, ":You have to be logged in to log out!", prefix=self.ircd.hostname)
            return
        self.socket.sendMessage("NOTICE", self.nickname, ":You are now logged out of \x02{}\x0F.".format(self.account), prefix=self.ircd.hostname)
        self.nickserv_id = None
        self.account = None
        self.checkNick()
        self.unregistered()
    
    def ns_registered(self, result, email, name):
        self.socket.sendMessage("NOTICE", self.nickname, ":Account \x02{}\x0F created with an email of \x02{}\x0F.".format(name,email), prefix=self.ircd.hostname)
        self.account = name
        self.nickserv_id = result
        self.registered()
    
    def ns_notregistered(self, result, email, name):
        self.socket.sendMessage("NOTICE", self.nickname, ":Account \x02{}\x0F with an email of \x02{}\x0F was \x1Fnot\x0F created. Please verify the account does not exist and try again later.".format(name,email), prefix=self.ircd.hostname)

    # ========================
    # === BIDSERV COMMANDS ===
    # ========================
    
    def bidserv_USAGE(self, prefix, params):
        self.socket.sendMessage("NOTICE", self.nickname, ":/msg BidServ COMMAND [OPTIONS] -- Use /msg BidServ HELP for more", prefix=self.ircd.hostname)