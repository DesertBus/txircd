# -*- coding: utf-8 -*-

from twisted.internet import reactor
from twisted.python import log
from twisted.words.protocols import irc
from txircd.user import IRCUser
from txircd.utils import irc_lower, chunk_message, now
from pbkdf2 import crypt
import inspect, random, yaml, os

NICKSERV_HELP_MESSAGE = """
\x02NickServ\x0F matches your IRC nickname to your Donor account, allowing for a painless 
auction process, as well as the peace of mind that nobody can use your nickname but you. 
To use a command, type \x02/msg NickServ \x1Fcommand\x0F. For more information on a command, type 
\x02/msg NickServ HELP \x1Fcommand\x0F.
""".replace("\n","")

BIDSERV_HELP_MESSAGE = """
\x02BidServ\x0F handles all of our fancy schmancy auction business. It's like the older, beefier brother of BidBot! 
To use a command, type \x02/msg BidServ \x1Fcommand\x0F. For more information on a command, type 
\x02/msg BidServ HELP \x1Fcommand\x0F. But let's be honest, you probably only care about 
\x02/bid \x1FAmount\x1F \x1F[Smack Talk]\x0F.
""".replace("\n","")

def _register_donor_account(txn, nickname, email, password, username, qmark):
    query = "INSERT INTO donors(email, password, display_name) VALUES({0},{0},{0})".format(qmark)
    txn.execute(query, (email, password, username))
    id = txn.lastrowid
    query = "INSERT INTO irc_nicks(donor_id, nick) VALUES({0},{0})".format(qmark)
    txn.execute(query, (id, nickname))
    return id

def _unregister_nickname(txn, donor_id, nickname, qmark):
    query = "DELETE FROM irc_nicks WHERE donor_id = {0} AND nick = {0}".format(qmark)
    txn.execute(query, (donor_id, nickname))
    return txn.rowcount
    
class DBUser(IRCUser):
    services = ["nickserv","bidserv"]

    # Start the party off right
    def __init__(self, parent, user, password, nick):
        # Service nicks are technically valid and not in use, but you can't have them.
        if irc_lower(nick) in self.services:
            parent.sendMessage(irc.ERR_NICKNAMEINUSE, nick, ":Nickname is already in use", prefix=parent.factory.server_name)
            parent.sendMessage("ERROR",":Closing Link: {}".format(nick))
            parent.transport.loseConnection()
            raise ValueError("Invalid nickname")
        IRCUser.__init__(self, parent, user, password, nick)
        self.auth_timer = None
        self.nickserv_id = None
        if password:
            if ":" in password:
                username, chaff, password = password.partition(":")
                self.auth(username, password)
            else:
                self.token(password)
        else:
            self.checkNick()
        #Auto-join #desertbus
        self.join("#desertbus",None)
    
    def service_prefix(self, service):
        return "{0}!{0}@{1}".format(service, self.ircd.server_name)
    
    # Called when they occur
    def registered(self):
        for channel in self.channels.iterkeys():
            c = self.ircd.channels[channel]
            mode = self.ircd.channel_auto_ops[irc_lower(self.nickname)] if irc_lower(self.nickname) in self.ircd.channel_auto_ops else "v"
            m, b, f = c.mode.combine("+{}".format(mode),[self.nickname],c.name)
            if m: # Should always be true!?
                c.log.write("[{:02d}:{:02d}:{:02d}] {} set modes {}\n".format(now().hour, now().minute, now().second, "BidServ", m))
                for u in c.users.itervalues():
                    u.sendMessage("MODE", m, to=c.name, prefix=self.service_prefix("BidServ"))
    
    def unregistered(self):
        for channel in self.channels.iterkeys():
            c = self.ircd.channels[channel]
            m, b, f = c.mode.combine("-{}".format(self.ircd.prefix_order),[self.nickname for _ in self.ircd.prefix_order],c.name)
            if m: # Should always be true!?
                c.log.write("[{:02d}:{:02d}:{:02d}] {} set modes {}\n".format(now().hour, now().minute, now().second, "BidServ", m))
                for u in c.users.itervalues():
                    u.sendMessage("MODE", m, to=c.name, prefix=self.service_prefix("BidServ"))
    
    # Restrict what people in the "need to identify" phase can do
    def handleCommand(self, command, prefix, params):
        # If we aren't waiting for auth, let them do as they please
        if self.auth_timer is None:
            IRCUser.handleCommand(self, command, prefix, params)
        # Allow some basic command, plus PRIVMSG so they can identify
        elif command in ["PING","PONG","NICK","PRIVMSG","QUIT","NS","NICKSERV","LOGIN"]:
            IRCUser.handleCommand(self, command, prefix, params)
        else:
            self.sendMessage("NOTICE", ":You can not use command \x02{}\x0F while identifying a registered nick.".format(command), prefix=self.service_prefix("NickServ"))
    
    # Aliases to make life easier on people
    def irc_NS(self, prefix, params):
        message = " ".join(params)
        self.irc_PRIVMSG(prefix, ["NickServ", message])
    
    def irc_NICKSERV(self, prefix, params):
        message = " ".join(params)
        self.irc_PRIVMSG(prefix, ["NickServ", message])
    
    def irc_LOGIN(self, prefix, params):
        message = " ".join(["LOGIN"] + params)
        self.irc_PRIVMSG(prefix, ["NickServ", message])
    
    def irc_BS(self, prefix, params):
        message = " ".join(params)
        self.irc_PRIVMSG(prefix, ["BidServ", message])
    
    def irc_BIDSERV(self, prefix, params):
        message = " ".join(params)
        self.irc_PRIVMSG(prefix, ["BidServ", message])
    
    def irc_BID(self, prefix, params):
        message = " ".join(["BID"] + params)
        self.irc_PRIVMSG(prefix, ["BidServ", message])
    
    # Voice registered users when they enter the room
    def join(self, channel, key):
        IRCUser.join(self, channel, key)
        if channel in self.channels and self.nickserv_id:
            c = self.ircd.channels[channel]
            mode = self.ircd.channel_auto_ops[irc_lower(self.nickname)] if irc_lower(self.nickname) in self.ircd.channel_auto_ops else "v"
            m, b, f = c.mode.combine("+{}".format(mode),[self.nickname],c.name)
            if m: # Should always be true!?
                c.log.write("[{:02d}:{:02d}:{:02d}] {} set modes {}\n".format(now().hour, now().minute, now().second, "BidServ", m))
                for u in c.users.itervalues():
                    u.sendMessage("MODE", m, to=c.name, prefix=self.service_prefix("BidServ"))
    
    # Track nick changes
    def irc_NICK(self, prefix, params):
        if params and irc_lower(params[0]) in self.services: # Can't use a service nick
            self.sendMessage(irc.ERR_NICKNAMEINUSE, params[0], ":Nickname is already in use", prefix=self.service_prefix("NickServ"))
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
            self.sendMessage("NOTICE", ":You can not PRIVMSG anybody but NickServ while identifying a registered nick.", prefix=self.service_prefix("NickServ"))
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
    
    def connectionLost(self, reason):
        if self.auth_timer: # cancel the nick change timer if a user quits before changing/identifying
            self.auth_timer.cancel()
            self.auth_timer = None
        IRCUser.connectionLost(self, reason)
    
    # =========================
    # === NICKSERV HANDLERS ===
    # =========================
    
    # We'll be needing these quite a bit
    def query(self, query, *args):
        query = query.format(self.ircd.db_marker)
        return self.ircd.db.runQuery(query, args)
    
    def failedAuth(self, result, reason):
        self.sendMessage("NOTICE", ":Failed Authorization [{}]".format(reason), prefix=self.service_prefix("NickServ"))
    
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
        if irc_lower(self.nickname).startswith(irc_lower(self.ircd.nickserv_guest_prefix)):
            return # Don't check guest nicks
        d = self.query("SELECT donor_id FROM irc_nicks WHERE nick = {0}", irc_lower(self.nickname))
        d.addCallback(self.beginVerify, self.nickname)
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
            self.sendMessage("NOTICE", ":You are now identified. Welcome, {}.".format(self.account), prefix=self.service_prefix("NickServ"))
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
        if irc_lower(nickname) != irc_lower(self.nickname):
            return # Changed nick too fast, don't even worry about it
        elif result:
            id = result[0][0]
            if self.nickserv_id and self.nickserv_id == id:
                if self.auth_timer: # Clear the timer
                    self.auth_timer.cancel()
                    self.auth_timer = None
                return # Already identified
            self.sendMessage("NOTICE", ":This is a registered nick. Please use \x02/msg nickserv login EMAIL PASSWORD\x0F to verify your identity", prefix=self.service_prefix("NickServ"))
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
        self.sendMessage("NOTICE", ":You are now identified. Welcome, {}.".format(self.account), prefix=self.service_prefix("NickServ"))
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
            nicklist = ", ".join([l[0] for l in result[:-1]])+", or "+result[-1][0] if len(result) > 1 else result[0][0]
            message = ":Warning: You already have {!s} registered nicks, so {} will not be protected. Please switch to {} to prevent impersonation!".format(self.ircd.nickserv_limit, nickname, nicklist)
            self.sendMessage("NOTICE", message, prefix=self.service_prefix("NickServ"))
        else:
            d = self.query("INSERT INTO irc_nicks(donor_id, nick) VALUES({0},{0})", self.nickserv_id, irc_lower(nickname))
            d.addCallback(self.successRegisterNick, nickname)
            d.addErrback(self.failedRegisterNick, nickname)
    
    def failedRegisterNick(self, result, nickname):
        self.sendMessage("NOTICE", ":Failed to register nick {} to account {}. Other users may still use it.".format(nickname, self.account), prefix=self.service_prefix("NickServ"))
    
    # Phase 4
    def successRegisterNick(self, result, nickname):
        self.sendMessage("NOTICE", ":Nickname {} is now registered to account {} and can not be used by any other user.".format(nickname, self.account), prefix=self.service_prefix("NickServ"))
    
    # =========================
    # === NICKSERV COMMANDS ===
    # =========================
    
    def nickserv_USAGE(self, prefix, params, command = None):
        if command:
            self.sendMessage("NOTICE", ":Unknown command \x02{}\x0F. \"/msg NickServ HELP\" for help.".format(command), prefix=self.service_prefix("NickServ"))
        else:
            self.sendMessage("NOTICE", ":Usage: /msg NickServ COMMAND [OPTIONS] -- Use /msg NickServ HELP for help", prefix=self.service_prefix("NickServ"))
    
    def nickserv_HELP(self, prefix, params):
        if not params:
            # Get all available commands
            methods = filter(lambda x: x[0].startswith("nickserv_"), inspect.getmembers(self, inspect.ismethod))
            # Prepare the format string to make everything nice
            fmtstr = "    {{:<{!s}}}  {{}}"
            name_length = max([len(m[0]) for m in methods]) - 9
            fmtstr = fmtstr.format(name_length)
            # Include the header
            lines = chunk_message(NICKSERV_HELP_MESSAGE, self.ircd.server_motd_line_length)
            lines.append("")
            # Add the commands and make them pretty
            for m in methods:
                if m[0] == "nickserv_USAGE" or m[0] == "nickserv_HELP":
                    continue
                doc = inspect.getdoc(m[1])
                lines.append(fmtstr.format(m[0][9:], doc.splitlines()[0]))
            # Now dump all that text to the user
            for l in lines:
                self.sendMessage("NOTICE", ":{}".format(l), prefix=self.service_prefix("NickServ"))
        else:
            # Try to load the command
            func = getattr(self, "nickserv_{}".format(params[0].upper()), None)
            if not func: # Doesn't exist :(
                self.sendMessage("NOTICE", ":Unknown command \x02{}\x0F. \"/msg NickServ HELP\" for help.".format(params[0]), prefix=self.service_prefix("NickServ"))
            else:
                doc = inspect.getdoc(func)
                lines = doc.splitlines()[1:] # Cut out the short help message
                for l in lines: # Print the long message
                    self.sendMessage("NOTICE", ":{}".format(l), prefix=self.service_prefix("NickServ"))
        
    def nickserv_REGISTER(self, prefix, params):
        """Create a donor account via IRC
        Syntax: \x02REGISTER \x1Fpassword\x1F \x1Femail\x1F \x1F[name]\x0F
        
        Creates a donor account with the specified email and password.
        Your current nick will be immediately associated with the new
        account and protected from impersonation. You'll also be voiced
        and allowed to bid in all auctions."""
        if len(params) < 2:
            self.sendMessage("NOTICE", ":Syntax: \x02REGISTER \x1Fpassword\x1F \x1Femail \x1F[name]\x0F", prefix=self.service_prefix("NickServ"))
            return
        email = params[1]
        password = crypt(params[0])
        name = " ".join(params[2:]) if len(params) > 2 else "Anonymous"
        d = self.ircd.db.runInteraction(_register_donor_account, self.nickname, email, password, name, self.ircd.db_marker)
        d.addCallback(self.ns_registered, email, name)
        d.addErrback(self.ns_notregistered, email, name)
    
    def nickserv_ID(self, prefix, params):
        """Alias of IDENTIFY
        Syntax: \x02ID \x1Femail\x1F:\x1Fpassword\x0F
        
        See IDENTIFY for more info"""
        self.nickserv_IDENTIFY(prefix, params)
    
    def nickserv_IDENTIFY(self, prefix, params):
        """Backwards compatible version of LOGIN
        Syntax: \x02IDENTIFY \x1Femail\x1F:\x1Fpassword\x0F
        
        Logs in to a donor account with the specified email and password.
        If it isn't already, your current nick will be associated with the
        account and protected from impersonation. You'll also be voiced
        and allowed to bid in all auctions."""
        if not params or params[0].find(":") < 0:
            self.sendMessage("NOTICE", ":Syntax: \x02IDENTIFY \x1Femail\x1F:\x1Fpassword\x0F", prefix=self.service_prefix("NickServ"))
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
            self.sendMessage("NOTICE", ":Syntax: \x02LOGIN \x1Femail\x1F \x1Fpassword\x0F", prefix=self.service_prefix("NickServ"))
            return
        self.auth(params[0], params[1])
    
    def nickserv_LOGOUT(self, prefix, params):
        """Log out of your donor account
        Syntax: \x02LOGOUT\x0F
        
        Logs out of whatever account you are in right now. Useful to
        prevent your roommate from bidding on auctions in your name."""
        if not self.account:
            self.sendMessage("NOTICE", ":You have to be logged in to log out!", prefix=self.service_prefix("NickServ"))
            return
        self.sendMessage("NOTICE", ":You are now logged out of \x02{}\x0F.".format(self.account), prefix=self.service_prefix("NickServ"))
        self.nickserv_id = None
        self.account = None
        self.checkNick()
        self.unregistered()
    
    def nickserv_LIST(self, prefix, params):
        """Lists all the nicknames registered to your account
        Syntax: \x02LIST\x0F
        
        Lists all the nicknames registered to your account"""
        if not self.nickserv_id:
            self.sendMessage("NOTICE", ":You have to be logged in to see your registered nicknames.", prefix=self.service_prefix("NickServ"))
            return
        d = self.query("SELECT nick FROM irc_nicks WHERE donor_id = {0}", self.nickserv_id)
        d.addCallback(self.ns_listnicks)
        d.addErrback(self.ns_listnickserr)
    
    def nickserv_DROP(self, prefix, params):
        """Unregisters a given nickname from your account
        Syntax: \x02DROP \x1Fnickname\x0F
        
        Unregisters the given nickname from your account,
        allowing other people to use it and giving you
        more space to register other nicknames."""
        if not self.nickserv_id:
            self.sendMessage("NOTICE", ":You have to be logged in to release a nickname.", prefix=self.service_prefix("NickServ"))
            return
        if not params:
            self.sendMessage("NOTICE", ":Syntax: \x02DROP \x1Fnickname\x0F", prefix=self.service_prefix("NickServ"))
            return
        nick = params[0]
        d = self.ircd.db.runInteraction(_unregister_nickname, self.nickserv_id, nick, self.ircd.db_marker)
        d.addCallback(self.ns_dropped, nick)
        d.addErrback(self.ns_notdropped, nick)
    
    def ns_registered(self, result, email, name):
        self.sendMessage("NOTICE", ":Account \x02{}\x0F created with an email of \x02{}\x0F.".format(name,email), prefix=self.service_prefix("NickServ"))
        self.account = name
        self.nickserv_id = result
        self.registered()
    
    def ns_notregistered(self, result, email, name):
        self.sendMessage("NOTICE", ":Account \x02{}\x0F with an email of \x02{}\x0F was \x1Fnot\x0F created. Please verify the account does not exist and try again later.".format(name,email), prefix=self.service_prefix("NickServ"))

    def ns_listnicks(self, result):
        message = ":Registered Nicknames: {}".format(", ".join([n[0] for n in result]))
        self.sendMessage("NOTICE", message, prefix=self.service_prefix("NickServ"))
    
    def ns_listnickserr(self, result):
        self.sendMessage("NOTICE", ":An error occured while retrieving your registered nicknames. Please try again later.", prefix=self.service_prefix("NickServ"))
    
    def ns_dropped(self, result, nick):
        if result:
            self.sendMessage("NOTICE", ":Nickname '{}' dropped.".format(nick), prefix=self.service_prefix("NickServ"))
        else:
            self.sendMessage("NOTICE", ":Nickname '{}' \x1Fnot\x1F dropped. Ensure it belongs to you.".format(nick), prefix=self.service_prefix("NickServ"))
    
    def ns_notdropped(self, result, nick):
        self.sendMessage("NOTICE", ":Nickname '{}' \x1Fnot\x1F dropped. Ensure it belongs to you.".format(nick), prefix=self.service_prefix("NickServ"))
    
    # ========================
    # === BIDSERV COMMANDS ===
    # ========================
      
    def bidserv_USAGE(self, prefix, params, command = None):
        if command:
            self.sendMessage("NOTICE", ":Unknown command \x02{}\x0F. \"/msg BidServ HELP\" for help.".format(command), prefix=self.service_prefix("BidServ"))
        else:
            self.sendMessage("NOTICE", ":Usage: /msg BidServ COMMAND [OPTIONS] -- Use /msg BidServ HELP for help", prefix=self.service_prefix("BidServ"))
    
    def bidserv_HELP(self, prefix, params):
        if not params:
            # Get all available commands
            methods = filter(lambda x: x[0].startswith("bidserv_"), inspect.getmembers(self, inspect.ismethod))
            # Prepare the format string to make everything nice
            fmtstr = "    {{:<{!s}}}  {{}}"
            name_length = max([len(m[0]) for m in methods]) - 8
            fmtstr = fmtstr.format(name_length)
            # Include the header
            lines = chunk_message(BIDSERV_HELP_MESSAGE, self.ircd.server_motd_line_length)
            lines.append("")
            # Add the commands and make them pretty
            for m in methods:
                if m[0] == "bidserv_USAGE" or m[0] == "bidserv_HELP":
                    continue
                doc = inspect.getdoc(m[1])
                lines.append(fmtstr.format(m[0][8:], doc.splitlines()[0]))
            # Now dump all that text to the user
            for l in lines:
                self.sendMessage("NOTICE", ":{}".format(l), prefix=self.service_prefix("BidServ"))
        else:
            # Try to load the command
            func = getattr(self, "bidserv_{}".format(params[0].upper()), None)
            if not func: # Doesn't exist :(
                self.sendMessage("NOTICE", ":Unknown command \x02{}\x0F. \"/msg BidServ HELP\" for help.".format(params[0]), prefix=self.service_prefix("BidServ"))
            else:
                doc = inspect.getdoc(func)
                lines = doc.splitlines()[1:] # Cut out the short help message
                for l in lines: # Print the long message
                    self.sendMessage("NOTICE", ":{}".format(l), prefix=self.service_prefix("BidServ"))
    
    def bidserv_BID(self, prefix, params):
        """Bid in the active auction
        Syntax: \x02BID \x1Famount\x1F \x1F[Smack Talk]\x0F
        
        During an auction, this command allows the user to place
        a bid. If the bid is higher than the current max bid,
        BidServ will echo it to the channel along with any provided
        smack talk."""
        if not params:
            self.sendMessage("NOTICE", ":Syntax: \x02BID \x1Famount\x1F \x1F[Smack Talk]\x0F".format(params[0]), prefix=self.service_prefix("BidServ"))
            return
        if not self.nickserv_id:
            self.sendMessage("NOTICE", ":You must be logged in to bid. \"/msg NickServ HELP\" for help.", prefix=self.service_prefix("BidServ"))
            return
        if not self.ircd.bidserv_auction_item:
            self.sendMessage("NOTICE", ":There is no auction going on right now.", prefix=self.service_prefix("BidServ"))
            return
        high_bid = self.ircd.bidserv_bids[-1]
        try:
            bid = float(params[0].lstrip("$"))
            bid = round(bid, 2)
        except:
            self.sendMessage("NOTICE", ":Bid amount must be a valid decimal.", prefix=self.service_prefix("BidServ"))
            return
        if bid >= self.ircd.bidserv_bid_limit:
            self.sendMessage("NOTICE", ":Let's be honest, you don't really have ${:,.2f} do you?".format(bid), prefix=self.service_prefix("BidServ"))
            return
        if bid <= high_bid["bid"]:
            self.sendMessage("NOTICE", ":Sorry, the high bid is already ${:,.2f} by {}".format(high_bid["bid"],high_bid["nick"]), prefix=self.service_prefix("BidServ"))
            return
        if bid < high_bid["bid"] + self.ircd.bidserv_min_increase:
            self.sendMessage("NOTICE", ":Sorry, the minimum bid increase is ${:,.2f}".format(self.ircd.bidserv_min_increase), prefix=self.service_prefix("BidServ"))
            return
        madness = ""
        levels = sorted(self.ircd.bidserv_madness_levels.items(), key=lambda t: t[0])
        for amount, name in levels:
            if amount <= high_bid["bid"] or bid < amount:
                continue
            if self.ircd.bidserv_display_all_madness:
                madness += "{}! ".format(name)
            else:
                madness = "{}! ".format(name)
        if high_bid["id"] == self.nickserv_id and self.ircd.bidserv_space_bid:
            madness += "{}! ".format(self.ircd.bidserv_space_bid)
        smack = " ".join(params[1:]).strip()
        self.ircd.bidserv_bids.append({
            "bid": bid,
            "id": int(self.nickserv_id),
            "nick": self.nickname
        })
        self.ircd.bidserv_auction_state = 0
        self.ircd.save_options() # Save auction state. Just in case.
        self.bs_broadcast(":\x02{}{} has the high bid of ${:,.2f}! {}\x0F".format(madness, self.nickname, bid, smack))
    
    def bidserv_HIGHBIDDER(self, prefix, params):
        """Get the high bidder in the current auction
        Syntax: \x02HIGHBIDDER\x0F
        
        Returns the high bidder in the current auction,
        along with the amount they bid."""
        if not self.ircd.bidserv_auction_item:
            self.sendMessage("NOTICE", ":There is no auction going on right now.", prefix=self.service_prefix("BidServ"))
        else:
            bid = self.ircd.bidserv_bids[-1]
            self.sendMessage("NOTICE", ":{} has the high bid of ${:,.2f}".format(bid["nick"], bid["bid"]), prefix=self.service_prefix("BidServ"))
    
    def bidserv_START(self, prefix, params):
        """Start an auction [Admin Only]
        Syntax: \x02START \x1FItem ID\x0F [Admin Only]
        
        Starts an auction with the given item ID.
        Restricted to admins."""
        if not irc_lower(self.nickname) in self.ircd.bidserv_admins:
            self.sendMessage("NOTICE", ":You are not an admin.", prefix=self.service_prefix("BidServ"))
            return
        if self.ircd.bidserv_auction_item is not None:
            self.sendMessage("NOTICE", ":There is already an auction occuring for item #{}.".format(self.ircd.bidserv_auction_item), prefix=self.service_prefix("BidServ"))
            return
        if not params:
            self.sendMessage("NOTICE", ":Syntax: \x02START \x1FItem ID\x0F", prefix=self.service_prefix("BidServ"))
            return
        d = self.query("SELECT id, name, sold, starting_bid FROM prizes WHERE id = {0}", params[0])
        d.addCallback(self.bs_start, params[0])
        d.addErrback(self.bs_failstart, params[0])
    
    def bidserv_ONCE(self, prefix, params):
        """Call "Going Once!" [Admin Only]
        Syntax: \x02ONCE\x0F [Admin Only]
        
        Calls "Going Once!" and increments auction state."""
        if not irc_lower(self.nickname) in self.ircd.bidserv_admins:
            self.sendMessage("NOTICE", ":You are not an admin.", prefix=self.service_prefix("BidServ"))
            return
        if self.ircd.bidserv_auction_item is None:
            self.sendMessage("NOTICE", ":There is no an auction occuring.", prefix=self.service_prefix("BidServ"))
            return
        if self.ircd.bidserv_auction_state != 0:
            self.sendMessage("NOTICE", ":We're not at the proper place to call \"Going Once!\".", prefix=self.service_prefix("BidServ"))
            return
        self.ircd.bidserv_auction_state = 1
        self.ircd.save_options() # Save auction state. Just in case.
        bid = self.ircd.bidserv_bids[-1]
        self.bs_broadcast(":\x02Going Once! To {} for ${:,.2f}!\x0F - Called by {}".format(bid["nick"],bid["bid"],self.nickname))
    
    def bidserv_TWICE(self, prefix, params):
        """Call "Going Twice!" [Admin Only]
        Syntax: \x02TWICE\x0F [Admin Only]
        
        Calls "Going Twice!" and increments auction state."""
        if not irc_lower(self.nickname) in self.ircd.bidserv_admins:
            self.sendMessage("NOTICE", ":You are not an admin.", prefix=self.service_prefix("BidServ"))
            return
        if self.ircd.bidserv_auction_item is None:
            self.sendMessage("NOTICE", ":There is no an auction occuring.", prefix=self.service_prefix("BidServ"))
            return
        if self.ircd.bidserv_auction_state != 1:
            self.sendMessage("NOTICE", ":We're not at the proper place to call \"Going Twice!\".", prefix=self.service_prefix("BidServ"))
            return
        self.ircd.bidserv_auction_state = 2
        self.ircd.save_options() # Save auction state. Just in case.
        bid = self.ircd.bidserv_bids[-1]
        self.bs_broadcast(":\x02Going Twice! To {} for ${:,.2f}!\x0F - Called by {}".format(bid["nick"],bid["bid"],self.nickname))
    
    def bidserv_SOLD(self, prefix, params):
        """Award the auction to the highest bidder [Admin Only]
        Syntax: \x02SOLD\x0F [Admin Only]
        
        Declares the auction as finished, cleans up variables, logs the bid
        history and adds the prize to the donors winnings in the database."""
        if not irc_lower(self.nickname) in self.ircd.bidserv_admins:
            self.sendMessage("NOTICE", ":You are not an admin.", prefix=self.service_prefix("BidServ"))
            return
        if self.ircd.bidserv_auction_item is None:
            self.sendMessage("NOTICE", ":There is not an auction occuring.", prefix=self.service_prefix("BidServ"))
            return
        if self.ircd.bidserv_auction_state != 2:
            self.sendMessage("NOTICE", ":We're not at the proper place to call \"Sold!\".", prefix=self.service_prefix("BidServ"))
            return
        bid = self.ircd.bidserv_bids[-1]
        d = self.query("UPDATE prizes SET donor_id = {0}, sold_amount = {0}, sold = 1 WHERE id = {0}",bid["id"],bid["bid"],self.ircd.bidserv_auction_item)
        d.addCallback(self.bs_sold)
        d.addErrback(self.bs_failsold)
    
    def bidserv_STOP(self, prefix, params):
        """Cancel the current auction [Admin Only]
        Syntax: \x02STOP\x0F [Admin Only]
        
        Stops the auction, awarding it to nobody, cleans
        up variables, and logs the bid history."""
        if not irc_lower(self.nickname) in self.ircd.bidserv_admins:
            self.sendMessage("NOTICE", ":You are not an admin.", prefix=self.service_prefix("BidServ"))
            return
        if self.ircd.bidserv_auction_item is None:
            self.sendMessage("NOTICE", ":There is not an auction occuring.", prefix=self.service_prefix("BidServ"))
            return
        try:
            with open(self.bs_log(self.ircd.bidserv_auction_item),"w") as f:
                yaml.dump(self.ircd.bidserv_bids, f, default_flow_style=False)
        except:
            self.bs_wallops(":Failed to save auction logs, you'll have to read the channel logs. Sorry :(")
        name = self.ircd.bidserv_auction_name
        bid = self.ircd.bidserv_bids[-1]
        self.ircd.bidserv_auction_state = 0
        self.ircd.bidserv_auction_item = None
        self.ircd.bidserv_auction_name = None
        self.ircd.bidserv_bids = []
        self.ircd.save_options() # Save auction state. Just in case.
        self.bs_broadcast(":\x02Auction for {} cancelled. Sorry!\x0F - Called by {}".format(name,self.nickname))
    
    def bidserv_REVERT(self, prefix, params):
        """Cancel the highest bid [Admin Only]
        Syntax: \x02REVERT\x0F [Admin Only]
        
        Purges the highest bid from the face of the earth,
        cleansing the bid pool to its prior pristine state."""
        if not irc_lower(self.nickname) in self.ircd.bidserv_admins:
            self.sendMessage("NOTICE", ":You are not an admin.", prefix=self.service_prefix("BidServ"))
            return
        if self.ircd.bidserv_auction_item is None:
            self.sendMessage("NOTICE", ":There is not an auction occuring.", prefix=self.service_prefix("BidServ"))
            return
        if len(self.ircd.bidserv_bids) < 2:
            self.sendMessage("NOTICE", ":There aren't enough bids to revert.", prefix=self.service_prefix("BidServ"))
            return
        bad = self.ircd.bidserv_bids.pop()
        bid = self.ircd.bidserv_bids[-1]
        self.ircd.bidserv_auction_state = 0
        self.bs_broadcast(":\x02Bid by {} for ${:,.2f} removed. New highest bid is by {} for ${:,.2f}!\x0F - Called by {}".format(bad["nick"],bad["bid"],bid["nick"],bid["bid"],self.nickname))
    
    def bs_failsold(self, result):
        bid = self.ircd.bidserv_bids[-1]
        self.bs_wallops(":Error updating database!! Stopping the auction regardless. Donor ID = {}, Nick = {}, Amount = ${:,.2f} - Good Luck!".format(bid["id"], bid["nick"], bid["bid"]))
        self.bs_sold(None)
    
    def bs_sold(self, result):
        name = self.ircd.bidserv_auction_name
        bid = self.ircd.bidserv_bids[-1]
        try:
            with open(self.bs_log(self.ircd.bidserv_auction_item),"w") as f:
                yaml.dump(self.ircd.bidserv_bids, f, default_flow_style=False)
        except:
            self.bs_wallops(":Failed to save auction logs, you'll have to read the channel logs. Sorry :(")
            log.err()
        self.ircd.bidserv_auction_state = 0
        self.ircd.bidserv_auction_item = None
        self.ircd.bidserv_auction_name = None
        self.ircd.bidserv_bids = []
        self.ircd.save_options() # Save auction state. Just in case.
        self.bs_broadcast(":\x02Sold! {} to {} for ${:,.2f}!\x0F - Called by {}".format(name, bid["nick"],bid["bid"],self.nickname))
    
    def bs_failstart(self, result, id):
        self.bs_wallops(":Error finding item ID #{}".format(id))
    
    def bs_start(self, result, id):
        if not result:
            self.bs_wallops(":Couldn't find item ID #{}".format(id))
        elif result[0][2]:
            self.bs_wallops(":Item #{!s}, {}, has already been sold.".format(result[0][0],result[0][1]))
        else:
            self.ircd.bidserv_auction_item = int(result[0][0])
            self.ircd.bidserv_auction_name = result[0][1]
            self.ircd.bidserv_bids = [{"bid": float(result[0][3]), "id": None, "nick": "Nobody"}]
            self.ircd.bidserv_auction_state = 0
            self.ircd.save_options() # Save auction state. Just in case.
            lines = [
                ":\x02Starting Auction: \"{}\"\x0F - Called by {}".format(result[0][1], self.nickname),
                ":\x02Make bids with \x1F/bid ###.##\x0F",
                ":\x02The minimum increment between bids is ${:,.2f}\x0F".format(self.ircd.bidserv_min_increase),
                ":\x02Only voiced (registered donor) users can bid - https://donor.desertbus.org/\x0F",
                ":\x02Please do not make any fake bids\x0F",
                ":\x02Beginning bidding at ${:,.2f}\x0F".format(float(result[0][3])),
            ]
            for l in lines:
                self.bs_broadcast(l)
    
    def bs_log(self, id):
        log = "{}/auction_{!s}.log".format(self.ircd.app_log_dir, id)
        count = 1
        while os.path.exists(log):
            log = "{}/auction_{!s}-{!s}.log".format(self.ircd.app_log_dir, id, count)
            count += 1
        return log
    
    def bs_wallops(self, message):
        for nick in self.ircd.bidserv_admins:
            if nick in self.ircd.users:
                u = self.ircd.users[nick]
                u.sendMessage("NOTICE", message, prefix=self.service_prefix("BidServ"))
    
    def bs_broadcast(self, message):
        for c in self.ircd.channels.itervalues():
            for u in c.users.itervalues():
                u.sendMessage("PRIVMSG", message, to=c.name, prefix=self.service_prefix("BidServ"))
