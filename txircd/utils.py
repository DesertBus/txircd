# -*- coding: utf-8 -*-
from functools import wraps
import inspect
from twisted.internet import reactor
from twisted.words.protocols import irc


class ParamParserError(Exception):
    pass


class NeedMoreParams(ParamParserError):
    pass


class TooManyParams(ParamParserError):
    pass


class ParamParser(object):
    def __init__(self, method):
        #todo: cleanup
        args, varargs, varkw, defaults = inspect.getargspec(method)
        if varkw:
            raise TypeError("Methods decorated with parse_args or multi may not use **kwargs")
        del args[:1] # self

        # amount of non-var-args
        fix_args = len(args)
        # amount of defaults
        num_def = len(defaults) if defaults else 0
        # minimum amount of arguments
        min_args = fix_args - num_def
        # maximum amount of arguments or -1 if varags or varkw is used
        max_args = -1 if varargs else len(args)

        # dictionary of default values
        if defaults:
            default_args = dict(zip(args[-num_def:], defaults))
        else:
            default_args = {}

        self.method = method
        self.argnames = args
        self.fix_args = fix_args
        self.min_args = min_args
        self.max_args = max_args
        self.default_args = default_args

    def parse(self, params):
        # check arg count
        arg_count = len(params)
        if arg_count < self.min_args:
            raise NeedMoreParams("Got %s params, expected a minimum of %s" % (arg_count, self.min_args))
        elif 0 < self.max_args < arg_count:
            raise TooManyParams("Got %s params, expected a maximum of %s" % (arg_count, self.max_args))
        else:
            kwargs = {}
            kwargs.update(self.default_args)
            kwargs.update(zip(self.argnames, params))
            rest = params[self.fix_args:]
            return rest, kwargs


def parse_args(method):
    parser = ParamParser(method)

    @wraps(method)
    def wrapper(self, prefix, params):
        try:
            rest, kwargs = parser.parse(params)
        except NeedMoreParams:
            return self.sendLine(irc.ERR_NEEDMOREPARAMS)
        except TooManyParams:
            return self.sendLine(irc.ERR_NEEDMOREPARAMS) # todo: is this the best response?
        # is the prefix really never used?
        return method(self, *rest, **kwargs)

    return wrapper


def multi(name, *methods):
    parsers = [ParamParser(method) for method in methods]

    def wrapper(self, prefix, params):
        for parser in parsers:
            try:
                rest, kwargs = parser.parse(params)
            except ParamParserError:
                continue
            return parser.method(self, *rest, **kwargs)
        return self.sendLine(irc.ERR_NEEDMOREPARAMS) # todo: just handle it like this?

    wrapper.__name__ = name
    return wrapper


def iterate_non_blocking(iterator):
    try:
        iterator.next()
    except StopIteration:
        return
    reactor.callLater(0, iterate_non_blocking, iterator)
