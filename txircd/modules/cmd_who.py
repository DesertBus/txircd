from twisted.words.protocols import irc
from txircd.modbase import Command

class WhoCommand(Command):
	def onUse(self, user, data):
		if "target" not in data:
			for u in self.ircd.users.itervalues():
				if "i" in u.mode:
					continue
				common_channel = False
				for c in self.channels.iterkeys():
					if c in u.channels:
						common_channel = True
						break
				if not common_channel:
					self.sendWhoLine(user, u, "*", None, data["filters"])
			user.sendMessage(irc.RPL_ENDOFWHO, self.nickname, "*", ":End of /WHO list.")
		else:
			if data["target"] in self.ircd.channels:
				cdata = self.ircd.channels[data["target"]]
				in_channel = cdata.name in user.channels # cache this value instead of searching self.channels every iteration
				if not in_channel and ("p" in cdata.mode or "s" in cdata.mode):
					irc.sendMessage(irc.RPL_ENDOFWHO, cdata.name, ":End of /WHO list.")
					return
				for u in cdata.users:
					self.sendWhoLine(user, u, cdata.name, cdata, data["filters"])
				user.sendMessage(irc.RPL_ENDOFWHO, cdata.name, ":End of /WHO list.")
			else:
				for u in self.ircd.users.itervalues():
					if fnmatch.fnmatch(irc_lower(u.nickname), irc_lower(params[0])) or fnmatch.fnmatch(irc_lower(u.hostname), irc_lower(params[0])):
						self.sendWhoLine(user, u, params[0], None, data["filters"])
				user.sendMessage(irc.RPL_ENDOFWHO, params[0], ":End of /WHO list.") # params[0] is used here for the target so that the original glob pattern is returned
	
	def processParams(self, user, params):
		if user.registered > 0:
			user.sendMessage(irc.ERR_NOTYETREGISTERED, "WHO", ":You have not registered")
			return {}
		if not params:
			return {
				"user": user
			}
		target = params[0]
		filters = params[1] if len(params) > 1 else ""
		if target[0][0] == "#" and target not in self.ircd.channels:
			user.sendMessage(irc.RPL_ENDOFWHO, channel, ":End of /WHO list")
			return {}
		return {
			"user": user,
			"target": target,
			"filters": filters
		}
	
	def sendWhoLine(self, user, targetUser, destination, channel, filters):
		udata = {
			"dest": destination,
			"nick": u.nickname,
			"ident": u.username,
			"host": u.hostname,
			"server": u.server,
			"away": "away" in u.metadata["ext"],
			"oper": "o" in u.mode,
			"status": u.status(channel.name)[0] if channel and u.status(channel.name) else "",
			"hopcount": 0,
			"gecos": u.realname,
		}
		extraData = { "user": user, "targetuser": targetUser, "cmdfilters": filters, "channel": channel, "data": udata }
		user.commandExtraHook("WHO", extraData)
		if not extraData["data"]:
			return
		data = extraData["data"]
		user.sendMessage(irc.RPL_WHOREPLY, data["dest"], data["ident"], data["host"], data["server"], data["nick"], "{}{}{}".format("G" if data["away"] else "H", "*" if data["oper"] else "", data["status"]), ":{} {}".format(data["hopcount"], data["gecos"]))

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
	
	def spawn(self):
		return {
			"commands": {
				"WHO": WhoCommand()
			}
		}
	
	def cleanup(self):
		del self.ircd.commands["WHO"]