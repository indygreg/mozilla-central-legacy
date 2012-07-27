============================================================
mozbuild and mach - Gateway to Developing Gecko Applications
============================================================

Welcome to mozbuild! mozbuild - and its frontend, mach - serve as your
gateway to the Mozilla build system and related developer tasks.

This document is tailored for people wanting to make changes to mozbuild
or who want to consume mozbuild from some other tool. If you are a
casual Mozilla developer, this document probably isn't right for you.

One of the goals of mach is for it to be self-documenting - you
shouldn't need to go looking in a README for more information. If you
found yourself here because mach wasn't helpful, you may want to improve
mach's output!

Source Code Structure
=====================

mozbuild is a Python package consisting of a number of modules. With the
lone exception of the mach frontend (which is in the root directory of
the tree), all of the mozbuild code is located under the directory
containing this file.

One of the important splits of code inside the *mozbuild* package is the
distinction between frontend and backend code. Frontend code is defined
as code that interacts with the user. It takes input from somewhere
(console, HTTP request, a pipe, etc), does something with it (makes a
call to a backend module), then does output processing (writes to the
terminal, generates a response message, etc).

This split between backend and frontend code is important because we
want to ensure that code we write to perform some action can be invoked
any number of ways. In other words, we don't want to constrain ourselves
to having a single frontend interface (*mach*). In the future, we could
have a Tcl/Tk, HTTP interface, etc. We want to loosely couple frontend
from backend code so new interfaces can be created easily and without
having to modify backend code (if possible).

Packages Overview
-----------------

* mozbuild.building - Modules related to building the tree. This is
  really a catch-all for code that doesn't fit anywhere else. If
  possible, code should go in another module.
* mozbuild.cli - Modules definining the *mach* command line interface
  and terminal interaction.
* mozbuild.compilation - Modules related to compiling code. This
  includes code for parsing output of 3rd party compilers, such as Clang
  and GCC.
* mozbuild.configuration - Modules related to configuring the build system.
* mozbuild.test - Test code for the overall *mozbuild* package. Files in
  here define all of our unit tests.
* mozbuild.testing - Modules related to running tests that are not part
  of mozbuild. This contains code for launching xpcshell and mochitests,
  for example.

The mach Driver
===============

The *mach* driver is the command line interface (CLI) for *mozbuild*.
The *mach* driver is invoked by running the *mach* script or from
instantiating the *Mach* class from the *mozbuild.cli.mach* module.

Implementing mach Commands
--------------------------

The *mach* driver follows the convention of popular tools like Git,
Subversion, and Mercurial and provides a common driver for multiple
sub-commands.

Modules inside *mozbuild.cli* typically contain 1 or more classes which
inherit from *mozbuild.cli.ArgumentProvider*. Modules that inherit from
this class are hooked up to the *mach* CLI driver. So, to add a new
sub-command/action to *mach*, one simply needs to create a new class in
the *mozbuild.cli* package which inherits from
*mozbuild.cli.ArgumentProvider*.

Currently, you also need to hook up some plumbing in
*mozbuild.cli.mach*. In the future, we hope to have automatic detection
of submodules.

Your command class performs the role of configuring the *mach* frontend
argument parser as well as providing the methods invoked if a command is
requested. These methods will take the user-supplied input, do something
(likely by calling a backend function in a separate module), then format
output to the terminal.

The plumbing to hook up the arguments to the *mach* driver involves
light magic. At *mach* invocation time, the driver creates a new
*argparse* instance. For each registered class that provides commands,
it calls the *populate_argparse* static method, passing it the parser
instance.

Your class's *populate_argparse* function should register sub-commands
with the parser.

For example, say you want to provide the *doitall* command. e.g. *mach
doitall*. You would create the module *mozbuild.cli.doitall* and this
module would contain the following class:

    from mozbuild.cli.base import ArgumentProvider

    class DoItAll(ArgumentProvider):
        def run(self, more=False):
            print 'I did it!'

        @staticmethod
        def populate_argparse(parser):
            # Create the parser to handle the sub-command.
            p = parser.add_parser('doitall', help='Do it all!')

            p.add_argument('more', action='store_true', default=False,
                help='Do more!')

            # Tell driver that the handler for this sub-command is the
            # method *run* on the class *DoItAll*.
            p.set_defaults(cls=DoItAll, method='run')

The most important line here is the call to *set_defaults*.
Specifically, the *cls* and *method* parameters, which tell the driver
which class to instantiate and which method to execute if this command
is requested.

The specified method will receive all arguments parsed from the command.
It is important that you use named - not positional - arguments for your
handler functions or things will blow up.

In the future, we may provide additional syntactical sugar to make all
this easier. For example, we may provide decorators on methods to hook
up commands and handlers.

Keeping Frontend Modules Small
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The frontends are all loaded when the CLI driver starts. Therefore,
there is potential for *import bloat*

We want the CLI driver to load quickly, so please try to avoid loading
external modules until needed. In other words, don't use a global
*import* when you can import from a handler.

Structured Logging
==================

One of the features of mozbuild is structured logging. Instead of
conventional logging where simple strings are logged, the internal
logging mechanism logs all events with the following pieces of
information:

* A string *action*
* A dict of log message fields
* A formatting string

Essentially, instead of assembling a human-readable string at
logging-time, you create an object holding all the pieces of data that
will constitute your logged event. For each unique type of logged event,
you assign an *action* name.

Depending on how logging is configured, your logged event could get
written a couple of different ways.

JSON Logging
------------

Where machines are the intended target of the logging data, a JSON
logger is configured. The JSON logger assembles an array consisting of
the following elements:

* Decimal wall clock time in seconds since UNIX epoch
* String *action* of message
* Object with structured message data

The JSON-serialized array is written to a configured file handle.
Consumers of this logging stream can just perform a readline() then feed
that into a JSON deserializer to reconstruct the original logged
message. They can key off the *action* element to determine how to
process individual events. There is no need to invent a parser.
Convenient, isn't it?

Logging for Humans
------------------

Where humans are the intended consumer of a log message, the structured
log message are converted to more human-friendly form. This is done by
utilizing the *formatting* string provided at log time. The logger
simply calls the *format* method of the formatting string, passing the
dict containing the message's fields.

When *mach* is used in a terminal that supports it, the logging facility
also supports terminal features such as colorization. This is done
automatically in the logging layer - there is no need to control this at
logging time.

In addition, messages intended for humans typically prepends every line
with the time passed since the application started.

Logging HOWTO
-------------

Structured logging piggybacks on top of Python's built-in logging
infrastructure provided by the *logging* package. We accomplish this by
taking advantage of *logging.Logger.log()*'s *extra* argument. To this
argument, we pass a dict with the fields *action* and *params*. These
are the string *action* and dict of message fields, respectively. The
formatting string is passed as the *msg* argument, like normal.

If you were logging to a logger directly, you would do something like:

    logger.log(logging.INFO, 'My name is {name}',
        extra={'action': 'my_name', 'params': {'name': 'Gregory'}})

The JSON logging would produce something like:

    [1339985554.306338, "my_name", {"name": "Gregory"}]

Human logging would produce something like:

     0.52 My name is Gregory

Since there is a lot of complexity using logger.log directly, it is
recommended to go through a wrapping layer that hides part of the
complexity for you. e.g.

    def log(self, level, action, params, format_str):
        self.logger.log(level, format_str,
            extra={'action': action, 'params': params)

