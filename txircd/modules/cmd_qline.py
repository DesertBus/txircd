from twisted.words.protocols import irc
from txircd.modbase import Command
from txircd.utils import epoch, now, irc_lower, parse_duration, CaseInsensitiveDictionary, VALID_NICKNAME

class QlineCommand(Command):
	def __init__(self):
		self.banList = CaseInsensitiveDictionary()
	
	def onUse(self, user, data):
		mask = data["mask"]
		if "reason" in data:
			self.banList[mask] = {
				"setter": user.nickname,
				"created": epoch(now()),
				"duration": data["duration"],
				"reason": data["reason"]
			}
			if "*" not in mask and "?" not in mask:
				if mask in self.ircd.users:
					self.remove_user(self.ircd.users[mask], data["reason"])
			else:
				now_banned = {}
				for uid, user in self.ircd.users.iteritems():
					reason = self.match_qline(user)
					if reason:
						now_banned[uid] = reason
				for uid, reason in now_banned.iteritems():
					self.remove_user(self.ircd.users[uid], reason)
	
	def processParams(self, user, params):
		if user.registered > 0:
			user.sendMessage(irc.ERR_NOTYETREGISTERED, "QLINE", ":You have not registered")
			return {}
		if "o" not in user.mode:
			user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the correct operator privileges")
			return {}
		if not params:
			user.sendMessage(irc.ERR_NEEDMOREPARAMS, "QLINE", ":Not enough parameters")
			return {}
		if len(params) < 3 and params[2]:
			self.expire_qlines()
			if params[0] in self.banList:
				user.sendMessage("NOTICE", ":*** Q:line already exists for {}; check /stats Q for a list of existing q:lines".format(params[0]))
				return {}
			if not params[0].replace("*", ""):
				user.sendMessage("NOTICE", ":*** That q:line will match all nicks!  Please check your nick mask and try again.")
				return {}
			if not VALID_NICKNAME.match(params[0].replace("*", "").replace("?", "a")):
				user.sendMessage("NOTICE", ":*** That isn't a valid nick mask and won't match any nicks.  Please check your nick mask and try again.")
				return {}
			return {
				"user": user,
				"mask": params[0],
				"duration": parse_duration(params[1]),
				"reason": " ".join(params[2:])
			}
		if params[0] not in self.banList:
			user.sendMessage("NOTICE", ":*** There is not a q:line set on {}; check /stats Q for a list of existing q:lines".format(params[0]))
			return {}
		return {
			"user": user,
			"mask": params[0]
		}
	
	def remove_user(self, user, reason):
		quit_to = set()
		for chan in user.channels.iterkeys():
			cdata = self.ircd.channels[chan]
			self.leave(chan)
			for u in cdata.users:
				quit_to.add(u)
		for u in quit_to:
			u.sendMessage("QUIT", ":Q:Lined: {}".format(reason), to=None, prefix=user.prefix())
		user.sendMessage("ERROR", ":Closing Link {} [Q:Lined: {}]".format(user.prefix(), data["reason"]), to=None, prefix=None)
		del self.ircd.users[user.nickname]
		user.socket.transport.loseConnection()
	
	def statsList(self, cmd, data):
		if cmd != "STATS":
			return
		if data["statstype"] != "Q":
			return
		udata = data["user"]
		self.expire_qlines()
		for mask, linedata in self.banList.iteritems():
			udata.sendMessage(irc.RPL_STATSQLINE, ":{} {} {} {} :{}".format(mask, linedata["created"], linedata["duration"], linedata["setter"], linedata["reason"]))
	
	def check_register(self, user):
		self.expire_qlines()
		reason = self.match_qline(user)
		if not reason:
			return True
		user.sendMessage("NOTICE", ":{}".format(self.ircd.client_ban_msg))
		user.sendMessage("ERROR", ":Closing Link: {} [Q:Lined: {}]".format(
	
	def match_qline(self, user):
		if "o" in user.mode:
			return None
		lowerNick = irc_lower(user.nickname)
		for mask, linedata in self.banList.iteritems():
			if fnmatch(lowerNick, mask):
				return linedata["reason"]
		return None
	
	def expire_qlines(self):
		current_time = epoch(now())
		expired = []
		for mask, linedata in self.banList.iteritems():
			if linedata["duration"] and current_time > linedata["created"] + linedata["duration"]:
				expired.append(mask)
		for mask in expired:
			del self.banList[mask]
	
	def blockNick(self, user, command, data):
		if command != "NICK":
			return data
		newNick = data["nick"]
		lowerNick = irc_lower(newNick)
		self.expire_qlines()
		for mask, linedata in self.banList.iteritems():
			if fnmatch(lowerNick, mask):
				user.sendMessage(irc.ERR_ERRONEUSNICKNAME, newNick, ":Invalid nickname: {}".format(linedata["reason"]))
				return {}
		return data

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
		self.qlineCmd = None
	
	def spawn(self):
		self.qlineCmd = QlineCommand()
		return {
			"commands": {
				"QLINE": self.qlineCmd
			},
			"actions": {
				"commandextra": [self.qlineCmd.statsList],
				"register": [self.qlineCmd.check_register],
				"commandpermission": [self.qlineCmd.blockNick]
			}
		}
	
	def cleanup(self):
		del self.ircd.commands["QLINE"]
		self.ircd.actions["commandextra"].remove(self.qlineCmd.statsList)
		self.ircd.actions["register"].remove(self.qlineCmd.check_register)
		self.ircd.actions["commandpermission"].remove(self.qlineCmd.blockNick)