from twisted.words.protocols import irc
from txircd.modbase import Command
from txircd.utils import epoch, irc_lower, now
from fnmatch import fnmatch

class WhoCommand(Command):
	def onUse(self, user, data):
		if "target" not in data:
			for u in self.ircd.users.itervalues():
				if "i" in u.mode:
					continue
				common_channel = False
				for c in user.channels.iterkeys():
					if c in u.channels:
						common_channel = True
						break
				if not common_channel:
					self.sendWhoLine(user, u, "*", None, data["filters"] if "filters" in data else "", data["fields"] if "fields" in data else "")
			user.sendMessage(irc.RPL_ENDOFWHO, "*", ":End of /WHO list.")
		else:
			if data["target"] in self.ircd.channels:
				cdata = self.ircd.channels[data["target"]]
				in_channel = cdata.name in user.channels # cache this value instead of searching self.channels every iteration
				if not in_channel and ("p" in cdata.mode or "s" in cdata.mode):
					irc.sendMessage(irc.RPL_ENDOFWHO, cdata.name, ":End of /WHO list.")
					return
				for u in cdata.users:
					self.sendWhoLine(user, u, cdata.name, cdata, data["filters"], data["fields"])
				user.sendMessage(irc.RPL_ENDOFWHO, cdata.name, ":End of /WHO list.")
			else:
				for u in self.ircd.users.itervalues():
					if fnmatch(irc_lower(u.nickname), irc_lower(params[0])) or fnmatch(irc_lower(u.hostname), irc_lower(params[0])):
						self.sendWhoLine(user, u, params[0], None, data["filters"], data["fields"])
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
		if "%" in filters:
			filters, fields = filters.split("%", 1)
		else:
			fields = ""
		if target[0][0] == "#" and target not in self.ircd.channels:
			user.sendMessage(irc.RPL_ENDOFWHO, channel, ":End of /WHO list")
			return {}
		return {
			"user": user,
			"target": target,
			"filters": filters,
			"fields": fields
		}
	
	def sendWhoLine(self, user, targetUser, destination, channel, filters, fields):
		displayChannel = destination
		if not channel:
			for chan in targetUser.channels.iterkeys():
				if chan in user.channels:
					displayChannel = chan
					break
			else:
				if "i" in user.mode:
					displayChannel = "*"
				else:
					displayChannel = targetUser.channels.keys()[0]
		udata = {
			"dest": destination,
			"nick": targetUser.nickname,
			"ident": targetUser.username,
			"host": targetUser.hostname,
			"ip": targetUser.ip,
			"server": targetUser.server,
			"away": "away" in targetUser.metadata["ext"],
			"oper": "o" in targetUser.mode,
			"idle": epoch(now()) - epoch(targetUser.lastactivity),
			"status": targetUser.status(channel.name)[0] if channel and targetUser.status(channel.name) else "",
			"hopcount": 0,
			"gecos": targetUser.realname,
			"account": targetUser.metadata["ext"]["accountname"] if "accountname" in targetUser.metadata["ext"] else "0",
			"channel": displayChannel
		}
		extraData = { "phase": "detect", "user": user, "targetuser": targetUser, "filters": filters, "fields": fields, "channel": channel, "data": udata }
		user.commandExtraHook("WHO", extraData)
		if not extraData["data"]:
			return
		extraData["phase"] = "display" # use a second round to potentially modify output after processing
		user.commandExtraHook("WHO", extraData)
		if not extraData["data"]:
			return # modules in the display phase can suppress normal output
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