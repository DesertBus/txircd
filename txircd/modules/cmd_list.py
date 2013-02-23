from twisted.words.protocols import irc
from txircd.modbase import Command
from txircd.utils import irc_lower
from fnmatch import fnmatch

class ListCommand(Command):
	def onUse(self, user, data):
		for cichanname, channel in self.ircd.channels.iteritems():
			if data["chanfilter"] is not None:
				filterMatch = False
				for filterEntry in data["chanfilter"]:
					if fnmatch(cichanname, filterEntry):
						filterMatch = True
						break
				if not filterMatch:
					continue
			cdata = {
				"name": channel.name,
				"users": len(channel.users),
				"modes": channel.mode,
				"topic": channel.topic if topic else ""
			}
			user.commandExtraHook("LIST", cdata)
			if not cdata:
				continue
			modeStr = "+"
			params = []
			for mode, param in cdata.mode.iteritems():
				if self.ircd.channel_mode_type[mode] != 0:
					modeStr.append(mode)
					params.append(param) if param
			if params:
				modeStr += " {}".format(" ".join(params))
			user.sendMessage(irc.RPL_LIST, cdata.name, cdata.users, ":[{}] {}".format(modeStr, cdata.topic))
		user.sendMessage(irc.RPL_LISTEND, ":End of channel list")
	
	def processParams(self, user, params):
		if user.registered > 0:
			user.sendMessage(irc.ERR_NOTYETREGISTERED, "LIST", ":You have not registered")
			return {}
		if params:
			chanFilter = params[0]
		else:
			chanFilter = None
		return {
			"user": user,
			"chanfilter": irc_lower(chanFilter).split(",")
		}

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
	
	def spawn(self):
		return {
			"commands": {
				"LIST": ListCommand()
			}
		}
	
	def cleanup(self):
		del self.ircd.commands["LIST"]