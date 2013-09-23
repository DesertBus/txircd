from twisted.python.logfile import DailyLogFile
from txircd.modbase import Module
from txircd.utils import CaseInsensitiveDictionary, now

class Logger(Module):
    # This is to help save from excessive disk I/O by holding the log files instead of constantly opening/flushing/closing them
    logfiles = CaseInsensitiveDictionary()
    
    def timePrefix(self):
        nowtime = now()
        return "[{:02d}:{:02d}:{:02d}]".format(nowtime.hour, nowtime.minute, nowtime.second)
    
    def writeLog(self, chan, line):
        line = "{} {}\n".format(self.timePrefix(), line)
        if chan.name not in self.logfiles:
            self.logfiles[chan.name] = DailyLogFile(chan.name, self.ircd.servconfig["app_log_dir"])
        logFile = self.logfiles[chan.name]
        if logFile.shouldRotate():
            logFile.rotate()
        logFile.write(line)
    
    def logMsg(self, cmd, data):
        if cmd in ["PRIVMSG", "NOTICE"]:
            if "targetchan" not in data or not data["targetchan"]:
                return
            user = data["user"]
            message = data["message"]
            if cmd == "PRIVMSG":
                if message[0:7] == "\x01ACTION":
                    message = data["message"][8:]
                    if message[-1] == "\x01":
                        message = message[:-1]
                    for index, chan in enumerate(data["targetchan"]):
                        prefix = self.ircd.prefixes[chan.users[user][0]][0] if user in chan.users and chan.users[user] else ""
                        if data["chanmod"][index]:
                            self.writeLog(chan, "*({}#) {}{} {}".format(data["chanmod"][index], prefix, user.nickname, message))
                        else:
                            self.writeLog(chan, "* {}{} {}".format(prefix, user.nickname, message))
                else:
                    for index, chan in enumerate(data["targetchan"]):
                        prefix = self.ircd.prefixes[chan.users[user][0]][0] if user in chan.users and chan.users[user] else ""
                        if data["chanmod"][index]:
                            self.writeLog(chan, "<{}#:{}{}> {}".format(data["chanmod"][index], prefix, user.nickname, message))
                        else:
                            self.writeLog(chan, "<{}{}> {}".format(prefix, user.nickname, message))
            elif cmd == "NOTICE":
                for index, chan in enumerate(data["targetchan"]):
                    prefix = self.ircd.prefixes[chan.users[user][0]][0] if user in chan.users and chan.users[user] else ""
                    if data["chanmod"][index]:
                        self.writeLog(chan, "-{}#:{}{}- {}".format(data["chanmod"][index], prefix, user.nickname, message))
                    else:
                        self.writeLog(chan, "-{}{}- {}".format(prefix, user.nickname, message))
        elif cmd == "PART":
            for chan in data["targetchan"]:
                self.writeLog(chan, "< {} has left the channel".format(data["user"].nickname))
        elif cmd == "KICK":
            self.writeLog(data["targetchan"], "< {} was kicked by {} ({})".format(data["targetuser"].nickname, data["user"].nickname, data["reason"]))
    
    def logJoin(self, user, channel):
        self.writeLog(channel, "> {} has joined the channel".format(user.nickname))
    
    def logNick(self, user, oldNick):
        for cdata in self.ircd.channels.itervalues():
            if user in cdata.users:
                self.writeLog(cdata, "! {} is now known as {}".format(oldNick, user.nickname))
    
    def logQuit(self, user, reason):
        for cdata in self.ircd.channels.itervalues():
            if user in cdata.users:
                self.writeLog(cdata, "< {} has quit: {}".format(user.nickname, reason))
    
    def logTopic(self, channel, topic, setter):
        self.writeLog(channel, "! {} has set the channel topic: {}".format(setter, topic))
    
    def logMode(self, channel, source, modeLine, modesChanged):
        # Filter out users so that we only work on channels
        try:
            channel.name
        except AttributeError:
            return
        self.writeLog(channel, "! {} has set modes {}".format(source, modeLine))
    
    def onDestroy(self, channel):
        if channel.name in self.logfiles:
            self.logfiles[channel.name].close()
            del self.logfiles[channel.name]
    
    def closeAllFiles(self):
        for logFile in self.logfiles.itervalues():
            logFile.close()
        self.logfiles.clear()

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
        self.logger = None
    
    def spawn(self):
        self.logger = Logger().hook(self.ircd)
        return {
            "actions": {
                "join": self.logger.logJoin,
                "nick": self.logger.logNick,
                "quit": self.logger.logQuit,
                "topic": self.logger.logTopic,
                "mode": self.logger.logMode,
                "commandextra": self.logger.logMsg,
                "chandestroy": self.logger.onDestroy
            }
        }
    
    def cleanup(self):
        self.logger.closeAllFiles()