# TODO: make sane before committing

from twisted.words.protocols import irc
from txircd.modbase import Mode
from txircd.utils import irc_lower, epoch, now, CaseInsensitiveDictionary
from fnmatch import fnmatch

class BanMode(Mode):
	def __init__(self):
		self.banMetadata = CaseInsensitiveDictionary()
	
	def checkSet(self, user, target, param):
		if " " in param:
			param = param[:param.index(" ")]
		if "b" in target.mode and len(target.mode["b"]) >= self.ircd.servconfig["channel_ban_list_size"]:
			return [False, param]
		if "!" not in param and "@" not in param:
			param = "{}!*@*".format(param)
		elif "@" not in param:
			param = "{}@*".format(param)
		elif "!" not in param:
			param = "*!{}".format(param)
		if target.name not in self.banMetadata:
			self.banMetadata[target.name] = {}
		self.banMetadata[target.name][param] = [user.nickname, epoch(now())]
		return [True, param]
	
	def checkUnset(self, user, target, param):
		if " " in param:
			param = param[:param.index(" ")]
		if "!" not in param and "@" not in param:
			param = "{}!*@*".format(param)
		elif "@" not in param:
			param = "{}@*".format(param)
		elif "!" not in param:
			param = "*!{}".format(param)
		for banmask in target.mode["b"]:
			if param == banmask:
				if param in self.banMetadata[target.name]:
					del self.banMetadata[target.name][param]
				return [True, param]
		return [False, param]
	
	def commandPermission(self, user, cmd, data):
		if cmd != "JOIN":
			return data
		channels = data["targetchan"]
		if "ban_evaluating" not in user.cache:
			user.cache["ban_evaluating"] = channels
			return "again"
		keys = data["keys"]
		remove = []
		hostmask = irc_lower(user.prefix())
		for chan in user.cache["ban_evaluating"]:
			if "b" in chan.mode:
				for mask in chan.mode["b"]:
					if fnmatch(hostmask, irc_lower(mask)):
						remove.append(chan)
						user.sendMessage(irc.ERR_BANNEDFROMCHAN, chan.name, ":Cannot join channel (You're banned)")
						break
		for chan in remove:
			index = channels.index(chan)
			channels.pop(index)
			keys.pop(index)
		data["targetchan"] = channels
		data["keys"] = keys
		del user.cache["ban_evaluating"]
		return data
	
	def showParam(self, user, target):
		if "b" in target.mode:
			for entry in target.mode["b"]:
				metadata = self.banMetadata[target.name][entry] if target.name in self.banMetadata and entry in self.banMetadata[target.name] else [ self.ircd.servconfig["server_name"], epoch(now()) ]
				user.sendMessage(irc.RPL_BANLIST, target.name, entry, metadata[0], str(metadata[1]))
			if target.name in self.banMetadata:
				removeMask = []
				for mask in self.banMetadata[target.name]:
					if mask not in target.mode["b"]:
						removeMask.append(mask)
				for mask in removeMask:
					del self.banMetadata[target.name][mask]
		elif target.name in self.banMetadata:
			del self.banMetadata[target.name] # clear all saved ban data if no bans are set on channel
		user.sendMessage(irc.RPL_ENDOFBANLIST, target.name, ":End of channel ban list")

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
	
	def spawn(self):
		if "channel_ban_list_size" not in self.ircd.servconfig:
			self.ircd.servconfig["channel_ban_list_size"] = 60
		return {
			"modes": {
				"clb": BanMode()
			}
		}
	
	def cleanup(self):
		self.ircd.removeMode("clb")