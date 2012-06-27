# -*- coding: utf-8 -*-
from collections import MutableMapping
from functools import wraps
import inspect
from twisted.internet import reactor
from twisted.python import log
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
        if args[0] != 'self':
            raise TypeError("Methods decorated with parse_args or multi must have 'self' as first argument")
        if args[1] != 'prefix':
            raise TypeError("Methods decorated with parse_args or multi must have 'prefix' as second argument")
        del args[:2] # self, prefix

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
        log.msg("Calling %r with %r *%r **%r" % (method.__name__, prefix, rest, kwargs))
        return method(self, prefix, *rest, **kwargs)

    return wrapper


def multi(name, *methods):
    parsers = [ParamParser(method) for method in methods]

    def wrapper(self, prefix, params):
        for parser in parsers:
            try:
                rest, kwargs = parser.parse(params)
            except ParamParserError:
                continue
            log.msg("Calling %r with %r *%r **%r" % (parser.method.__name__, prefix, rest, kwargs))
            return parser.method(self, prefix, *rest, **kwargs)
        return self.sendLine(irc.ERR_NEEDMOREPARAMS) # todo: just handle it like this?

    wrapper.__name__ = name
    return wrapper


def iterate_non_blocking(iterator):
    try:
        iterator.next()
    except StopIteration:
        return
    reactor.callLater(0, iterate_non_blocking, iterator)


class CaseInsensitiveDictionary(MutableMapping):
    def __init__(self):
        self._data = {}

    def __repr__(self):
        return repr(self._data)

    def __delitem__(self, key):
        try:
            del self._data[key.lower()]
        except KeyError:
            raise KeyError(key)

    def __getitem__(self, key):
        try:
            return self._data[key.lower()]
        except KeyError:
            raise KeyError(key)

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data)

    def __setitem__(self, key, value):
        self._data[key.lower()] = value


class DefaultCaseInsensitiveDictionary(CaseInsensitiveDictionary):
    def __init__(self, default_factory):
        self._default_factory = default_factory
        super(DefaultCaseInsensitiveDictionary, self).__init__()

    def __getitem__(self, key):
        try:
            return super(DefaultCaseInsensitiveDictionary, self).__getitem__(key)
        except KeyError:
            value = self[key] = self._default_factory()
            return value
