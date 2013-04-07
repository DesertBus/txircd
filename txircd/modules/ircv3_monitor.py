from twisted.words.protocols import irc
from txircd.modbase import Command
from txircd.utils import chunk_message, irc_lower

# These numerics are as stated in the IRCv3 MONITOR specification: http://ircv3.atheme.org/specification/monitor-3.2
irc.RPL_MONONLINE = "730"
irc.RPL_MONOFFLINE = "731"
irc.RPL_MONLIST = "732"
irc.RPL_ENDOFMONLIST = "733"
irc.ERR_MONLISTFULL = "734"

class MonitorCommand(Command):
	def __init__(self, limit):
		self.limit = limit
		self.watching = {}
		self.watched_by = {}
		self.watch_masks = {} # Keep the case in one of the versions
	
	def onUse(self, user, data):
		modifier = data["modifier"]
		if modifier == "+":
			targetlist = data["targetlist"]
			discard = []
			for target in targetlist:
				if len(target) > 32 or " " in target:
					discard.append(target)
			for target in discard:
				targetlist.remove(target)
			if user not in self.watch_masks:
				self.watch_masks[user] = []
			if user not in self.watching:
				self.watching[user] = []
			if self.limit and len(self.watch_masks[user]) + len(targetlist) > self.limit:
				user.sendMessage(irc.ERR_MONLISTFULL, str(self.limit), ",".join(targetlist), ":Monitor list is full")
				return
			online = []
			offline = []
			for target in targetlist:
				lowerTarget = irc_lower(target)
				if lowerTarget not in self.watching[user]:
					self.watch_masks[user].append(target)
					self.watching[user].append(lowerTarget)
					if lowerTarget not in self.watched_by:
						self.watched_by[lowerTarget] = []
					self.watched_by[lowerTarget].append(user)
				if target in self.ircd.users:
					online.append(target)
				else:
					offline.append(target)
			if online:
				onLines = chunk_message(" ".join(online), 400)
				for line in onLines:
					user.sendMessage(irc.RPL_MONONLINE, ":{}".format(line.replace(" ", ",")))
			if offline:
				offLines = chunk_message(" ".join(offline), 400)
				for line in offLines:
					user.sendMessage(irc.RPL_MONOFFLINE, ":{}".format(line.replace(" ", ",")))
		elif modifier == "-":
			targetlist = data["targetlist"]
			if user not in self.watch_masks or user not in watching:
				return
			for target in targetlist:
				lowerTarget = irc_lower(target)
				if lowerTarget in self.watching:
					self.watching[user].remove(lowerTarget)
					watchList = self.watch_masks[user]
					for mask in watchList:
						if irc_lower(mask) == lowerTarget:
							self.watch_masks[user].remove(mask)
				if lowerTarget in self.watched_by:
					self.watched_by[lowerTarget].remove(user)
		elif modifier == "C":
			self.watch_masks[user] = []
			for target in self.watching[user]:
				self.watched_by[target].remove(user)
			self.watching[user] = []
		elif modifier == "L":
			if user in self.watch_masks:
				userlist = chunk_message(" ".join(self.watch_masks[user]), 400)
				for line in userlist:
					user.sendMessage(irc.RPL_MONLIST, ":{}".format(line.replace(" ", ",")))
			user.sendMessage(irc.RPL_ENDOFMONLIST, ":End of MONITOR list")
		elif modifier == "S":
			if user in self.watch_masks:
				online = []
				offline = []
				for target in self.watch_masks[user]:
					if target in self.ircd.users:
						online.append(target)
					else:
						offline.append(target)
				if online:
					onlineLines = chunk_message(" ".join(online), 400)
					for line in onlineLines:
						user.sendMessage(irc.RPL_MONONLINE, ":{}".format(line.replace(" ", ",")))
				if offline:
					offlineLines = chunk_message(" ".join(offline), 400)
					for line in offlineLines:
						user.sendMessage(irc.RPL_MONOFFLINE, ":{}".format(line.replace(" ", ",")))
	
	def processParams(self, user, params):
		if not params:
			user.sendMessage(irc.ERR_NEEDMOREPARAMS, "MONITOR", ":Not enough parameters")
			return {}
		if params[0] in ["C", "L", "S"]:
			return {
				"user": user,
				"modifier": params[0]
			}
		if params[0] in ["+", "-"]:
			return {
				"user": user,
				"modifier": params[0],
				"targetlist": params[1].split(",")
			}
		return {}
	
	def listWatching(self, user):
		if user in self.watching:
			return self.watching[user]
		return []
	
	def listWatchedBy(self, user):
		user = irc_lower(user)
		if user in self.watched_by:
			return self.watched_by[user]
		return []
	
	def notifyConnect(self, user):
		lowerNick = irc_lower(user.nickname)
		if lowerNick in self.watched_by:
			for watcher in self.watched_by[lowerNick]:
				watcher.sendMessage(irc.RPL_MONONLINE, ":{}".format(user.nickname))
		return True
	
	def notifyQuit(self, user, reason):
		lowerNick = irc_lower(user.nickname)
		if lowerNick in self.watched_by:
			for watcher in self.watched_by[lowerNick]:
				watcher.sendMessage(irc.RPL_MONOFFLINE, ":{}".format(user.nickname))
	
	def notifyNick(self, user, oldNick):
		lowerNick = irc_lower(user.nickname)
		lowerOldNick = irc_lower(oldNick)
		if lowerOldNick in self.watched_by:
			for watcher in self.watched_by[lowerOldNick]:
				watcher.sendMessage(irc.RPL_MONOFFLINE, ":{}".format(oldNick))
		if lowerNick in self.watched_by:
			for watcher in self.watched_by[lowerNick]:
				watcher.sendMessage(irc.RPL_MONONLINE, ":{}".format(user.nickname))

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
		self.monitor_cmd = None
	
	def spawn(self):
		if "client_monitor_limit" not in self.ircd.servconfig:
			self.ircd.servconfig["client_monitor_limit"] = None # Default to no limit
		try:
			mon_limit = int(self.ircd.servconfig["client_monitor_limit"])
		except TypeError:
			mon_limit = None # When we do not enforce a limit, we don't show a value for MONITOR in ISUPPORT; the ISUPPORT code hides values of None
		except ValueError:
			mon_limit = None # Invalid arguments go to the default
		self.ircd.isupport["MONITOR"] = mon_limit
		self.monitor_cmd = MonitorCommand(mon_limit)
		return {
			"commands": {
				"MONITOR": self.monitor_cmd
			},
			"actions": {
				"monitorwatching": [self.monitor_cmd.listWatching],
				"monitorwatchedby": [self.monitor_cmd.listWatchedBy],
				"register": [self.monitor_cmd.notifyConnect],
				"quit": [self.monitor_cmd.notifyQuit],
				"nick": [self.monitor_cmd.notifyNick]
			}
		}
	
	def cleanup(self):
		del self.ircd.commands["MONITOR"]
		self.ircd.actions["monitorwatching"].remove(self.monitor_cmd.listWatching)
		self.ircd.actions["monitorwatchedby"].remove(self.monitor_cmd.listWatchedBy)
		self.ircd.actions["register"].remove(self.monitor_cmd.notifyConnect)
		self.ircd.actions["quit"].remove(self.monitor_cmd.notifyQuit)
		self.ircd.actions["nick"].remove(self.monitor_cmd.notifyNick)