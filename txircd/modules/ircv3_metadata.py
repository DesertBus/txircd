from twisted.words.protocols import irc
from txircd.modbase import Command
from fnmatch import fnmatch

# As per the IRCv3.2 METADATA spec, numerics 760-769 must be reserved for
# metadata: http://ircv3.atheme.org/specification/metadata-3.2
# The defined numerics are as follows:
irc.RPL_WHOISKEYVALUE = "760"
irc.RPL_KEYVALUE = "761"
irc.RPL_METADATAEND = "762"
irc.ERR_TARGETINVALID = "765"
irc.ERR_NOMATCHINGKEYS = "766"
irc.ERR_KEYINVALID = "767"
irc.ERR_KEYNOTSET = "768"
irc.ERR_KEYNOPERMISSION = "769"

class MetadataCommand(Command):
	def onUse(self, user, data):
		subcmd = data["subcmd"]
		target = data["target"]
		
		if subcmd == "LIST":
			namespaceList = ["server", "client", "user", "ext"]
			if "o" in user.mode:
				namespaceList.append("private")
			if data["filter"]:
				filter = data["filter"]
				encounteredItem = False
				for namespace in namespaceList:
					for key, value in target.metadata[namespace].iteritems():
						if fnmatch("{}.{}".format(namespace, key), filter):
							encounteredItem = True
							if value:
								user.sendMessage(irc.RPL_KEYVALUE, "{}.{}".format(namespace, key), ":{}".format(value))
							else:
								user.sendMessage(irc.RPL_KEYVALUE, "{}.{}".format(namespace, key))
				if encounteredItem:
					user.sendMessage(irc.RPL_METADATAEND, ":End of metadata")
				else:
					user.sendMessage(irc.ERR_NOMATCHINGKEYS, filter, ":no matching keys")
			else:
				encounteredItem = False
				for namespace in namespaceList:
					for key, value in target.metadata[namespace].iteritems():
						encounteredItem = True
						if value:
							user.sendMessage(irc.RPL_KEYVALUE, "{}.{}".format(namespace, key), ":{}".format(value))
						else:
							user.sendMessage(irc.RPL_KEYVALUE, "{}.{}".format(namespace, key))
				if encounteredItem:
					user.sendMessage(irc.RPL_METADATAEND, ":End of metadata")
				else:
					user.sendMessage(irc.ERR_NOMATCHINGKEYS, "*", ":no matching keys")
		elif subcmd == "SET":
			namespace, key = data["key"].split(".", 1)
			if namespace not in ["user", "client"]:
				user.sendMessage(irc.ERR_KEYNOPERMISSION, data["targetname"], key, ":permission denied")
				return
			# This may be restricted later to only keys in the key registry; for now, I don't think allowing
			# whatever keys in the user-settable namespaces is a major problem. //EA
			if data["value"]:
				target.setMetadata(namespace, key, data["value"])
				user.sendMessage(irc.RPL_KEYVALUE, "{}.{}".format(namespace, key), ":{}".format(data["value"]))
			else:
				target.delMetadata(namespace, key)
				user.sendMessage(irc.RPL_KEYVALUE, "{}.{}".format(namespace, key))
			user.sendMessage(irc.RPL_METADATAEND, ":end of metadata")
		elif subcmd == "CLEAR":
			for namespace in ["client", "user"]:
				removeKeys = target.metadata[namespace].keys()
				for key in removeKeys:
					target.delMetadata(namespace, key)
					user.sendMessage(irc.RPL_KEYVALUE, data["targetname"], "{}.{}".format(namespace, key))
			user.sendMessage(irc.RPL_METADATAEND, ":end of metadata")
	
	def processParams(self, user, params):
		if user.registered > 0:
			user.sendMessage(irc.ERR_NOTYETREGISTERED, "METADATA", ":You have not registered")
			return {}
		if not params or len(params) < 2:
			user.sendMessage(irc.ERR_NEEDMOREPARAMS, "METADATA", ":Not enough parameters")
			return {}
		target = None
		if params[0] in self.ircd.channels:
			target = self.ircd.channels[params[0]]
		elif params[0] in self.ircd.users:
			target = self.ircd.users[params[0]]
		else:
			user.sendMessage(irc.ERR_TARGETINVALID, params[0], ":invalid metadata target")
			return {}
		subcmd = params[1].upper()
		if subcmd == "LIST":
			return {
				"user": user,
				"targetname": params[0],
				"target": target,
				"subcmd": "LIST",
				"filter": params[2] if len(params) >= 3 else None
			}
		if subcmd == "SET":
			if len(params) < 3:
				user.sendMessage(irc.ERR_NEEDMOREPARAMS, "METADATA", ":Not enough parameters")
				return {}
			if "o" not in user.mode:
				try:
					if not user.hasAccess(target.name, self.ircd.servconfig["channel_metadata_set_level"]):
						user.sendMessage(irc.ERR_CHANOPRIVSNEEDED, target.name, ":You do not have access to set metadata on this channel")
						return {}
				except AttributeError: # in this case, it's a user, not a channel
					if user != target:
						user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the correct operator privileges")
						return {}
			if "." not in params[2]:
				user.sendMessage(irc.ERR_KEYINVALID, params[2], ":invalid metadata key")
				return {}
			return {
				"user": user,
				"targetname": params[0],
				"target": target,
				"subcmd": "SET",
				"key": params[2],
				"value": params[3] if len(params) >= 4 else None
			}
		if subcmd == "CLEAR":
			if "o" not in user.mode and user != target:
				user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the correct operator privileges")
				return {}
			return {
				"user": user,
				"targetname": params[0],
				"target": target,
				"subcmd": "CLEAR"
			}
		user.sendMessage(irc.ERR_NEEDMOREPARAMS, "METADATA", ":Incorrect metadata subcommand") # borrowing this numeric is fine
		return {}
	
	def capRequest(self, user, capability):
		return True
	
	def capAcknowledge(self, user, capability):
		return False
	
	def capRequestRemove(self, user, capability):
		return True
	
	def capAcknowledgeRemove(self, user, capability):
		return False
	
	def capClear(self, user, capability):
		return True
	
	def whoisSendMetadata(self, cmd, data):
		if cmd != "WHOIS":
			return
		user = data["user"]
		target = data["targetuser"]
		namespaceList = ["server", "client", "user", "ext"]
		if "o" in user.mode:
			namespaceList.append("private")
		for namespace in namespaceList:
			for key, value in target.metadata[namespace].iteritems():
				user.sendMessage(irc.RPL_WHOISKEYVALUE, key, ":{}".format(value))
	
	def notify(self, target, namespace, key, oldValue, value):
		try:
			target.nickname
		except AttributeError: # don't process channels
			return
		source = None
		if namespace in ["client", "user"]:
			source = target.nickname
		elif namespace in ["server", "ext"]:
			source = self.ircd.servconfig["server_name"]
		else:
			return
		watcherList = []
		for modfunc in self.ircd.actions["monitorwatchedby"]:
			watcherList += modfunc(target.nickname)
		watchers = set(watcherList)
		if not value and key not in target.metadata[namespace]:
			for u in watchers:
				if "cap" in u.cache and "metadata-notify" in u.cache["cap"]:
					u.sendMessage("METADATA", source, target.nickname, "{}.{}".format(namespace, key))
		else:
			for u in watchers:
				if "cap" in u.cache and "metadata-notify" in u.cache["cap"]:
					u.sendMessage("METADATA", source, target.nickname, "{}.{}".format(namespace, key), ":{}".format(value))

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
		self.metadata_cmd = None
	
	def spawn(self):
		if "channel_metadata_set_level" not in self.ircd.servconfig:
			self.ircd.servconfig["channel_metadata_set_level"] = "o"
		self.metadata_cmd = MetadataCommand()
		if "cap" not in self.ircd.module_data_cache:
			self.ircd.module_data_cache["cap"] = {}
		self.ircd.module_data_cache["cap"]["metadata-notify"] = self.metadata_cmd
		return {
			"commands": {
				"METADATA": self.metadata_cmd
			},
			"actions": {
				"metadataupdate": [self.metadata_cmd.notify]
			}
		}
	
	def cleanup(self):
		del self.ircd.commands["METADATA"]
		del self.ircd.module_data_cache["cap"]["metadata-notify"]